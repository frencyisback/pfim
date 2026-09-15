"""Service: PerformanceService. Combine the pure finance engine with trades, income events and
prices to calculate security and portfolio returns. All metrics use EUR positions and income,
ensuring different currencies can be compared and aggregated consistently.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal

from sqlalchemy.orm import Session

from app.finance.income import current_yield, yield_on_cost
from app.finance.periods import trailing_year_start
from app.finance.portfolio import (
    PositionTracker,
    as_eur_priced,
    calculate_position,
    calculate_position_eur,
)
from app.finance.returns import annualize, money_weighted_return
from app.finance.returns import simple_return as simple_return_fn
from app.finance.returns import time_weighted_return, total_return
from app.repositories.income_event_repo import IncomeEventRepository
from app.repositories.portfolio_cost_repo import PortfolioCostRepository
from app.repositories.price_repo import PriceRepository
from app.repositories.security_repo import SecurityRepository
from app.repositories.trade_repo import TradeRepository
from app.schemas.performance import (
    CostBasis,
    IncomeBasis,
    PerformanceMetadata,
    PerformanceMetrics,
    PortfolioPerformance,
)
from app.schemas.report import PortfolioValuationFallback, PortfolioValuationMetadata
from app.utils.currency import to_eur
from app.utils.errors import NotFoundError, ValidationErrorPFIM


class PerformanceService:
    def __init__(self, db: Session):
        self.db = db
        self.security_repo = SecurityRepository(db)
        self.trade_repo = TradeRepository(db)
        self.price_repo = PriceRepository(db)
        self.income_repo = IncomeEventRepository(db)
        self.portfolio_cost_repo = PortfolioCostRepository(db)

    @staticmethod
    def _resolve_bases(
        *,
        income_basis: IncomeBasis | None,
        cost_basis: CostBasis | None,
        gross: bool | None,
    ) -> tuple[IncomeBasis, CostBasis]:
        """Normalize the current contract and legacy gross alias. Defaults preserve net income
        with costs excluded. Contradictory values for the alias and new income axis produce an
        explicit HTTP 400 instead of depending on parameter order.
        """

        if income_basis not in {None, "net", "gross"}:
            raise ValidationErrorPFIM(
                "income_basis must be 'net' or 'gross'",
                detail={"income_basis": income_basis},
            )
        if cost_basis not in {None, "exclude", "include"}:
            raise ValidationErrorPFIM(
                "cost_basis must be 'exclude' or 'include'",
                detail={"cost_basis": cost_basis},
            )

        alias_basis: IncomeBasis | None = None
        if gross is not None:
            alias_basis = "gross" if gross else "net"
            if income_basis is not None and income_basis != alias_basis:
                raise ValidationErrorPFIM(
                    "The gross and income_basis parameters are inconsistent",
                    detail={"gross": gross, "income_basis": income_basis},
                )
        return income_basis or alias_basis or "net", cost_basis or "exclude"

    @staticmethod
    def _income_amount(event, income_basis: IncomeBasis) -> Decimal:
        return Decimal(event.total_eur if income_basis == "gross" else event.net_amount_eur)

    @staticmethod
    def _metadata(
        *, income_basis: IncomeBasis, cost_basis: CostBasis, portfolio: bool
    ) -> PerformanceMetadata:
        costs = "included" if cost_basis == "include" else "excluded"
        recurring = (
            "included_at_portfolio_level"
            if portfolio and cost_basis == "include"
            else "excluded_at_portfolio_level" if portfolio else "not_allocated_to_security"
        )
        metric_bases = {
            "simple_return": "price_only; independent_of_income_and_cost_basis",
            "realized_gain_loss": "fifo_gross; excludes_trade_and_recurring_costs",
            "total_income_received": f"income_{income_basis}",
            "yield_on_cost": f"trailing_12m_income_{income_basis}; costs_independent",
            "current_yield": f"trailing_12m_income_{income_basis}; costs_independent",
            "total_return": f"income_{income_basis}; trade_costs_{costs}",
            "money_weighted_return": f"income_{income_basis}; trade_costs_{costs}",
        }
        if portfolio:
            metric_bases.update(
                {
                    "total_return": (
                        f"income_{income_basis}; trade_costs_{costs}; " f"recurring_costs_{costs}"
                    ),
                    "time_weighted_return": (
                        f"income_{income_basis}; trade_costs_{costs}; " f"recurring_costs_{costs}"
                    ),
                    "total_return_annualized": "annualized_total_return",
                    "time_weighted_return_annualized": "annualized_time_weighted_return",
                }
            )
        return PerformanceMetadata(
            income_basis=income_basis,
            cost_basis=cost_basis,
            trade_costs_scope=(
                "included_in_total_return_and_cash_flow_metrics"
                if cost_basis == "include"
                else "excluded_from_performance_metrics"
            ),
            recurring_costs_scope=recurring,
            metric_bases=metric_bases,
        )

    def _current_price_eur(self, security, *, as_of: dt.date) -> Decimal | None:
        """Latest known price converted using its frozen native price and exchange rate. Do not
        quantize the product before multiplying by quantity, as unit rounding would be
        amplified on large positions. The persisted EUR price remains informational.
        """
        latest_price = self.price_repo.get_latest(security.id, as_of=as_of)
        return (
            to_eur(Decimal(latest_price.price_close), Decimal(latest_price.fx_rate))
            if latest_price
            else None
        )

    @classmethod
    def _annualized_income(
        cls, events: list, income_basis: IncomeBasis, *, as_of: dt.date
    ) -> Decimal:
        """Sum income on the requested basis over the trailing year. Use the same
        trailing_year_start boundary as ReportService.dividends_analysis. Filter the caller's
        preloaded income list instead of querying again.
        """
        start = trailing_year_start(as_of)
        return sum(
            (
                cls._income_amount(e, income_basis)
                for e in events
                if start <= e.payment_date <= as_of
            ),
            Decimal(0),
        )

    def security_performance(
        self,
        security_id: int,
        *,
        income_basis: IncomeBasis | None = None,
        cost_basis: CostBasis | None = None,
        gross: bool | None = None,
    ) -> PerformanceMetrics:
        """Security performance metrics. simple_return and total_return measure only the open
        position, using remaining FIFO cost; fully closed positions return null and carry zero
        weight in the portfolio aggregate. Realized results are exposed separately in
        realized_gain_loss. MWR/IRR uses all cash flows and includes realized gains.
        """
        income_basis, cost_basis = self._resolve_bases(
            income_basis=income_basis, cost_basis=cost_basis, gross=gross
        )
        security = self.security_repo.get(security_id)
        if security is None:
            raise NotFoundError(
                f"Security {security_id} not found", detail={"security_id": security_id}
            )

        as_of = dt.date.today()
        trades = self.trade_repo.list(security_id=security_id, date_to=as_of)
        if not trades:
            raise ValidationErrorPFIM(
                f"No trades recorded for security {security_id}",
                detail={"security_id": security_id},
            )

        return self._metrics(
            security,
            trades,
            self.income_repo.list(security_id=security_id, date_to=as_of),
            self._current_price_eur(security, as_of=as_of),
            as_of=as_of,
            income_basis=income_basis,
            cost_basis=cost_basis,
            costs_by_trade=(
                self._costs_by_trade(trade_ids={trade.id for trade in trades})
                if cost_basis == "include"
                else {}
            ),
        )

    def _metrics(
        self,
        security,
        trades: list,
        events: list,
        current_price_eur: Decimal | None,
        *,
        as_of: dt.date,
        income_basis: IncomeBasis,
        cost_basis: CostBasis,
        costs_by_trade: dict[int, Decimal],
    ) -> PerformanceMetrics:
        """Calculate performance from caller-provided data. Separating reads lets a
        single-security request load its own data while a portfolio request loads all
        securities in batches without repeated queries.
        """
        position_eur = calculate_position_eur(trades)
        position_native = calculate_position(trades)  # Quantity only (currency invariant).

        total_income = sum(
            (self._income_amount(e, income_basis) for e in events),
            Decimal(0),
        )
        trade_costs = sum((costs_by_trade.get(t.id, Decimal(0)) for t in trades), Decimal(0))
        included_trade_costs = trade_costs if cost_basis == "include" else Decimal(0)

        # Value the entire position, matching total cost basis and received income. Total-to-total
        # metrics such as total return and current yield use this value; only simple return and
        # average price operate per unit.
        #
        #
        current_value_eur = (
            current_price_eur * position_native.quantity if current_price_eur is not None else None
        )

        simple_ret = None
        total_ret = None
        if current_price_eur is not None and position_eur.average_cost > 0:
            simple_ret = simple_return_fn(
                current_price_eur, position_eur.average_cost, dividends=Decimal("0")
            )
            total_ret = total_return(
                position_eur.total_invested,
                current_value_eur,
                net_dividends=total_income - included_trade_costs,
            )

        # YoC and current yield use total income over total values (§9.6, §9.7). Using average
        # cost and unit price would multiply the percentage by the holding quantity and diverge
        # from /reports/dividends-analysis, which uses totals.
        #
        #
        annualized_income = self._annualized_income(events, income_basis, as_of=as_of)
        yoc = None
        cur_yield = None
        if position_eur.total_invested > 0 and annualized_income > 0:
            yoc = yield_on_cost(annualized_income, position_eur.total_invested)
        if current_value_eur is not None and current_value_eur > 0 and annualized_income > 0:
            cur_yield = current_yield(annualized_income, current_value_eur)

        mwr = None
        cash_flows = []
        for trade in trades:
            amount = Decimal(trade.total_eur)
            cost = (
                costs_by_trade.get(trade.id, Decimal(0)) if cost_basis == "include" else Decimal(0)
            )
            cash_flows.append(
                (trade.date, -(amount + cost))
                if trade.type == "buy"
                else (trade.date, amount - cost)
            )
        cash_flows += [
            (event.payment_date, self._income_amount(event, income_basis)) for event in events
        ]
        if position_native.quantity > 0 and current_value_eur is not None:
            cash_flows.append((as_of, current_value_eur))
        try:
            if len(cash_flows) >= 2:
                mwr = money_weighted_return(cash_flows)
        except ValueError:
            mwr = None  # Cash flows unsuitable for calculation (e.g. all have the same sign).

        return PerformanceMetrics(
            security_id=security.id,
            ticker=security.ticker,
            simple_return=simple_ret,
            total_return=total_ret,
            money_weighted_return=mwr,
            yield_on_cost=yoc,
            current_yield=cur_yield,
            realized_gain_loss=position_eur.realized_gain_loss,
            total_income_received=total_income,
            metadata=self._metadata(
                income_basis=income_basis, cost_basis=cost_basis, portfolio=False
            ),
        )

    def _portfolio_value_and_invested_series_details(
        self,
        dates: Iterable[dt.date],
        *,
        include_same_day_trades: bool,
        trades: list | None = None,
        prices: list | None = None,
    ) -> tuple[
        dict[dt.date, Decimal],
        dict[dt.date, list[int]],
        dict[dt.date, Decimal],
    ]:
        """Value all positions in EUR on every requested date in one pass. With
        include_same_day_trades=False, value immediately before that day's trades for TWR.
        Fall back to remaining FIFO cost when no price exists. Load trades and prices once and
        advance cursors, updating FIFO for each trade. Also return IDs of securities valued at
        cost so reports explicitly identify estimates.
        """
        sorted_dates = sorted(set(dates))
        if not sorted_dates:
            return {}, {}, {}

        trades_by_security: dict[int, list] = defaultdict(list)
        # The cursor still applies each as_of cutoff. Both reads intentionally have no global
        # filter to keep SQL cost constant across date counts/ranges and avoid different plans for
        # short and long series.
        #
        all_trades = trades if trades is not None else self.trade_repo.list()
        for trade in all_trades:  # Already sorted by (date, id).
            trades_by_security[trade.security_id].append(trade)

        prices_by_security: dict[int, list] = defaultdict(list)
        all_prices = prices if prices is not None else self.price_repo.list_all()
        for price in all_prices:
            prices_by_security[price.security_id].append(price)

        totals: dict[dt.date, Decimal] = {d: Decimal("0") for d in sorted_dates}
        invested_totals: dict[dt.date, Decimal] = {d: Decimal("0") for d in sorted_dates}
        cost_fallbacks: dict[dt.date, list[int]] = {d: [] for d in sorted_dates}

        for security_id, trades in trades_by_security.items():
            prices = prices_by_security.get(security_id, [])
            tracker = PositionTracker()
            trade_cursor = 0
            price_cursor = 0
            last_price = None

            for as_of in sorted_dates:
                while trade_cursor < len(trades) and (
                    trades[trade_cursor].date <= as_of
                    if include_same_day_trades
                    else trades[trade_cursor].date < as_of
                ):
                    tracker.apply(as_eur_priced(trades[trade_cursor]))
                    trade_cursor += 1
                while price_cursor < len(prices) and prices[price_cursor].date <= as_of:
                    last_price = prices[price_cursor]
                    price_cursor += 1

                quantity = tracker.quantity
                if quantity <= 0:
                    continue
                invested_totals[as_of] += tracker.total_invested
                if last_price is not None:
                    totals[as_of] += (
                        to_eur(Decimal(last_price.price_close), Decimal(last_price.fx_rate))
                        * quantity
                    )
                else:
                    totals[as_of] += tracker.total_invested
                    cost_fallbacks[as_of].append(security_id)

        return totals, cost_fallbacks, invested_totals

    def portfolio_value_series_details(
        self, dates: Iterable[dt.date], *, include_same_day_trades: bool
    ) -> tuple[dict[dt.date, Decimal], dict[dt.date, list[int]]]:
        """Portfolio values and FIFO-cost fallback metadata. The internal pass also computes
        invested capital for period reports; this wrapper preserves the existing public
        contract for other callers.
        """
        totals, cost_fallbacks, _ = self._portfolio_value_and_invested_series_details(
            dates, include_same_day_trades=include_same_day_trades
        )
        return totals, cost_fallbacks

    def portfolio_value_and_invested_series(
        self,
        dates: Iterable[dt.date],
        *,
        include_same_day_trades: bool,
        trades: list | None = None,
        prices: list | None = None,
    ) -> tuple[dict[dt.date, Decimal], dict[dt.date, Decimal]]:
        """Market value and open FIFO cost on the same dates. Compute both in one pass,
        optionally using data already loaded by the report, so daily averages do not add
        queries as the period grows.
        """
        values, _, invested = self._portfolio_value_and_invested_series_details(
            dates,
            include_same_day_trades=include_same_day_trades,
            trades=trades,
            prices=prices,
        )
        return values, invested

    def portfolio_value_series(
        self, dates: Iterable[dt.date], *, include_same_day_trades: bool
    ) -> dict[dt.date, Decimal]:
        """Compatibility wrapper for calculations needing values only. User-facing reports use
        portfolio_value_series_details to disclose FIFO-cost fallback estimates.
        """
        totals, _ = self.portfolio_value_series_details(
            dates, include_same_day_trades=include_same_day_trades
        )
        return totals

    def _portfolio_value_as_of(self, as_of: dt.date, *, include_same_day_trades: bool) -> Decimal:
        """Market value in EUR on one date. For multiple dates, use portfolio_value_series to
        load the data only once.
        """
        return self.portfolio_value_series(
            [as_of], include_same_day_trades=include_same_day_trades
        )[as_of]

    def _costs_by_trade(self, *, trade_ids: set[int] | None = None) -> dict[int, Decimal]:
        """EUR costs by trade, fetched in one query."""
        totals: dict[int, Decimal] = defaultdict(Decimal)
        for cost in self.trade_repo.list_all_costs():
            if trade_ids is not None and cost.trade_id not in trade_ids:
                continue
            totals[cost.trade_id] += Decimal(cost.amount_eur)
        return totals

    def _external_flows_by_date(
        self,
        *,
        net_of_costs: bool = False,
        income_basis: IncomeBasis = "net",
        costs_by_trade: dict[int, Decimal] | None = None,
        recurring_costs: list | None = None,
        as_of: dt.date | None = None,
        trades: list | None = None,
        income_events: list | None = None,
    ) -> dict[dt.date, Decimal]:
        """External portfolio flows in EUR by date. Positive means capital contributed for
        purchases; negative means withdrawals through sales or income paid to reference
        accounts. With net_of_costs=True, purchases include fees, sales withdraw less, and
        recurring costs add capital without buying securities. income_basis independently
        selects gross or net income. Pre-flow TWR valuation must include the same income and
        subtract the same costs so only securities remain after the flow.
        """
        as_of = as_of or dt.date.today()
        trades = trades if trades is not None else self.trade_repo.list(date_to=as_of)
        trade_ids = {trade.id for trade in trades}
        flows: dict[dt.date, Decimal] = defaultdict(Decimal)
        if net_of_costs and costs_by_trade is None:
            costs_by_trade = self._costs_by_trade(trade_ids=trade_ids)
        costs_by_trade = costs_by_trade or {}

        for t in trades:
            amount = Decimal(t.total_eur)
            costs = costs_by_trade.get(t.id, Decimal("0"))
            flows[t.date] += (amount + costs) if t.type == "buy" else -(amount - costs)
        events = (
            income_events if income_events is not None else self.income_repo.list(date_to=as_of)
        )
        for e in events:
            if e.payment_date > as_of:
                continue
            flows[e.payment_date] -= self._income_amount(e, income_basis)

        if net_of_costs:
            if recurring_costs is None:
                recurring_costs = self.portfolio_cost_repo.list(date_to=as_of)
            for c in recurring_costs:
                flows[c.date] += abs(Decimal(c.amount_eur))
        return dict(flows)

    def _first_trade_date(
        self, *, as_of: dt.date | None = None, trades: list | None = None
    ) -> dt.date | None:
        """Date of the first purchase or sale, when the portfolio starts to exist. Income
        payments must not establish the start: earlier income on a missing or previously
        closed position would create a zero-capital start with undefined TWR.
        """
        all_trades = trades if trades is not None else self.trade_repo.list(date_to=as_of)
        dates = [t.date for t in all_trades if as_of is None or t.date <= as_of]
        return min(dates) if dates else None

    def investment_period_days(self, *, as_of: dt.date | None = None) -> int | None:
        """Days from the first trade through today, used to annualize cumulative returns."""
        as_of = as_of or dt.date.today()
        first = self._first_trade_date(as_of=as_of)
        if first is None:
            return None
        days = (as_of - first).days
        return days if days > 0 else None

    def portfolio_twr(
        self,
        *,
        net_of_costs: bool = False,
        income_basis: IncomeBasis = "net",
        costs_by_trade: dict[int, Decimal] | None = None,
        recurring_costs: list | None = None,
        as_of: dt.date | None = None,
        period_start: dt.date | None = None,
    ) -> Decimal | None:
        """Portfolio TWR removes cash-flow timing and size effects for comparison with market
        indices. Return None without sufficient data. net_of_costs=True includes trade and
        recurring costs. Optional period_start limits the inclusive interval ending at as_of;
        if no position exists then, start at the first later trade opening one, because zero
        initial capital has no defined return.
        """
        values = self._portfolio_twr_variants(
            net_modes=(net_of_costs,),
            income_basis=income_basis,
            costs_by_trade=costs_by_trade,
            recurring_costs=recurring_costs,
            as_of=as_of,
            period_start=period_start,
        )
        return values[net_of_costs]

    def portfolio_twr_pair(
        self,
        *,
        income_basis: IncomeBasis = "net",
        costs_by_trade: dict[int, Decimal] | None = None,
        recurring_costs: list | None = None,
        as_of: dt.date | None = None,
        period_start: dt.date | None = None,
        trades: list | None = None,
        income_events: list | None = None,
        prices: list | None = None,
    ) -> tuple[Decimal | None, Decimal | None]:
        """Compute gross and net TWR together using shared reads and valuations. Cost reports
        require both variants; sharing preloaded data preserves the same mathematical
        definitions without duplicate queries.
        """
        values = self._portfolio_twr_variants(
            net_modes=(False, True),
            income_basis=income_basis,
            costs_by_trade=costs_by_trade,
            recurring_costs=recurring_costs,
            as_of=as_of,
            period_start=period_start,
            trades=trades,
            income_events=income_events,
            prices=prices,
        )
        return values[False], values[True]

    def _portfolio_twr_variants(
        self,
        *,
        net_modes: tuple[bool, ...],
        income_basis: IncomeBasis,
        costs_by_trade: dict[int, Decimal] | None,
        recurring_costs: list | None,
        as_of: dt.date | None,
        period_start: dt.date | None,
        trades: list | None = None,
        income_events: list | None = None,
        prices: list | None = None,
    ) -> dict[bool, Decimal | None]:
        """Shared TWR implementation using optionally preloaded data."""
        period_end = as_of or dt.date.today()
        all_trades = trades if trades is not None else self.trade_repo.list(date_to=period_end)
        all_trades = [trade for trade in all_trades if trade.date <= period_end]
        all_events = (
            income_events
            if income_events is not None
            else self.income_repo.list(date_to=period_end)
        )
        all_events = [event for event in all_events if event.payment_date <= period_end]
        income_by_date: dict[dt.date, Decimal] = defaultdict(Decimal)
        for event in all_events:
            income_by_date[event.payment_date] += self._income_amount(event, income_basis)

        first_trade = min((trade.date for trade in all_trades), default=None)
        empty = {mode: None for mode in net_modes}
        if first_trade is None:
            return empty

        requested_start = period_start
        initial_start = (
            first_trade
            if requested_start is None or requested_start <= first_trade
            else requested_start
        )
        if period_end <= initial_start:
            return empty

        gross_flows = self._external_flows_by_date(
            income_basis=income_basis,
            as_of=period_end,
            trades=all_trades,
            income_events=all_events,
        )
        flow_maps: dict[bool, dict[dt.date, Decimal]] = {False: gross_flows}

        if True in net_modes:
            trade_ids = {trade.id for trade in all_trades}
            if costs_by_trade is None:
                costs_by_trade = self._costs_by_trade(trade_ids=trade_ids)
            if recurring_costs is None:
                recurring_costs = self.portfolio_cost_repo.list(date_to=period_end)
            flow_maps[True] = self._external_flows_by_date(
                net_of_costs=True,
                income_basis=income_basis,
                costs_by_trade=costs_by_trade,
                recurring_costs=recurring_costs,
                as_of=period_end,
                trades=all_trades,
                income_events=all_events,
            )

        relevant_flow_dates = {
            date
            for mode in net_modes
            for date in flow_maps[mode]
            if initial_start <= date <= period_end
        }
        candidate_open_dates = {
            trade.date for trade in all_trades if initial_start <= trade.date <= period_end
        }
        closing_dates = candidate_open_dates | {initial_start, period_end}
        pre_flow_dates = relevant_flow_dates | {initial_start}

        closing, _, _ = self._portfolio_value_and_invested_series_details(
            closing_dates,
            include_same_day_trades=True,
            trades=all_trades,
            prices=prices,
        )
        pre_flow, _, _ = self._portfolio_value_and_invested_series_details(
            pre_flow_dates,
            include_same_day_trades=False,
            trades=all_trades,
            prices=prices,
        )

        # If the portfolio already existed at the requested opening, include that day's flows.
        # Otherwise, start the calculation at the first position-creating trade, as for cumulative
        # TWR.
        opened_by_trade = initial_start == first_trade
        actual_start = initial_start
        if not opened_by_trade and pre_flow[initial_start] <= 0:
            actual_start = next(
                (
                    date
                    for date in sorted(candidate_open_dates)
                    if closing.get(date, Decimal("0")) > 0
                ),
                initial_start,
            )
            opened_by_trade = closing.get(actual_start, Decimal("0")) > 0

        if period_end <= actual_start:
            return empty

        # Do not concatenate segments separated by a full closure. Remaining quantity must be
        # positive: quote/execution differences cannot create fictitious capital after the entire
        # position is sold.
        #
        if any(closing[date] <= 0 for date in candidate_open_dates if date >= actual_start):
            return empty

        results: dict[bool, Decimal | None] = {}
        for mode in net_modes:
            flows = flow_maps[mode]
            # The flow difference contains exactly the costs already aggregated by date, including
            # recurring costs. No second aggregation can diverge.
            #
            costs_by_date = (
                {
                    date: amount - gross_flows.get(date, Decimal("0"))
                    for date, amount in flows.items()
                }
                if mode
                else {}
            )
            flow_dates = [
                date
                for date in sorted(flows)
                if (date > actual_start if opened_by_trade else date >= actual_start)
                and date <= period_end
            ]
            starting_value = closing[actual_start] if opened_by_trade else pre_flow[actual_start]
            if starting_value <= 0:
                results[mode] = None
                continue

            opening_factor = Decimal("1")
            if opened_by_trade:
                # Opening is a separate case: exclude the initial flow, and include opening-day income and
                # costs exactly once in (V0 + I0) / (V0 + C0). Subsequent periods start from security
                # value V0, excluding costs from capital.
                #
                opening_factor = (
                    starting_value + income_by_date.get(actual_start, Decimal("0"))
                ) / (starting_value + costs_by_date.get(actual_start, Decimal("0")))

            # P is security value before today's trades. A flow of G - I + C requires pre-flow P + I -
            # C, giving P + G and leaving no income or costs in the next period's capital. Each mode
            # has its own map.
            #
            adjusted_pre_flow = {
                date: pre_flow[date]
                + income_by_date.get(date, Decimal("0"))
                - costs_by_date.get(date, Decimal("0"))
                for date in flow_dates
            }
            try:
                subsequent_return = time_weighted_return(
                    starting_value=starting_value,
                    ending_value=closing[period_end],
                    cash_flows=[(date, flows[date]) for date in flow_dates],
                    prices_at_flow_dates=adjusted_pre_flow,
                    period_start=actual_start,
                    period_end=period_end,
                )
                results[mode] = opening_factor * (Decimal("1") + subsequent_return) - Decimal("1")
            except ValueError:
                results[mode] = None
        return results

    @staticmethod
    def _annualized(cumulative: Decimal | None, days: int | None) -> Decimal | None:
        if cumulative is None or days is None:
            return None
        try:
            return annualize(cumulative, days)
        except ValueError:
            return None

    def portfolio_mwr(
        self,
        *,
        income_basis: IncomeBasis = "net",
        include_costs: bool = False,
        costs_by_trade: dict[int, Decimal] | None = None,
        recurring_costs: list | None = None,
        as_of: dt.date | None = None,
    ) -> Decimal | None:
        """Portfolio MWR/IRR measures the return earned by capital, including contribution
        timing. Interpret it alongside TWR.
        """
        as_of = as_of or dt.date.today()
        trades = self.trade_repo.list(date_to=as_of)
        if include_costs and costs_by_trade is None:
            costs_by_trade = self._costs_by_trade(trade_ids={trade.id for trade in trades})
        costs_by_trade = costs_by_trade or {}
        cash_flows: list[tuple[dt.date, Decimal]] = []
        for t in trades:
            amount = Decimal(t.total_eur)
            cost = costs_by_trade.get(t.id, Decimal(0)) if include_costs else Decimal(0)
            cash_flows.append(
                (t.date, -(amount + cost)) if t.type == "buy" else (t.date, amount - cost)
            )
        for e in self.income_repo.list(date_to=as_of):
            cash_flows.append((e.payment_date, self._income_amount(e, income_basis)))
        if include_costs:
            if recurring_costs is None:
                recurring_costs = self.portfolio_cost_repo.list(date_to=as_of)
            cash_flows.extend(
                (cost.date, -abs(Decimal(cost.amount_eur))) for cost in recurring_costs
            )

        final_value = self._portfolio_value_as_of(as_of, include_same_day_trades=True)
        if final_value > 0:
            cash_flows.append((as_of, final_value))

        if len(cash_flows) < 2:
            return None
        try:
            return money_weighted_return(cash_flows)
        except ValueError:
            return None

    def portfolio_performance(
        self,
        *,
        income_basis: IncomeBasis | None = None,
        cost_basis: CostBasis | None = None,
        gross: bool | None = None,
    ) -> PortfolioPerformance:
        """Metrics for every security with trades, plus portfolio totals. Batch-load trades,
        income, and latest prices for the whole portfolio to avoid repeated per-security
        queries.
        """
        income_basis, cost_basis = self._resolve_bases(
            income_basis=income_basis, cost_basis=cost_basis, gross=gross
        )
        as_of = dt.date.today()
        include_costs = cost_basis == "include"

        all_trades = self.trade_repo.list(date_to=as_of)
        costs_by_trade = (
            self._costs_by_trade(trade_ids={trade.id for trade in all_trades})
            if include_costs
            else {}
        )
        recurring_costs = self.portfolio_cost_repo.list(date_to=as_of) if include_costs else []

        trades_by_security: dict[int, list] = defaultdict(list)
        for trade in all_trades:
            trades_by_security[trade.security_id].append(trade)

        events_by_security: dict[int, list] = defaultdict(list)
        for event in self.income_repo.list(date_to=as_of):
            events_by_security[event.security_id].append(event)

        latest_prices = self.price_repo.latest_by_security(as_of=as_of)

        metrics: list[PerformanceMetrics] = []
        total_invested = Decimal("0")
        total_current_value = Decimal("0")
        fallback_securities: list[PortfolioValuationFallback] = []

        for security in self.security_repo.list():
            trades = trades_by_security.get(security.id)
            if not trades:
                continue

            latest_price = latest_prices.get(security.id)
            current_price_eur = (
                to_eur(Decimal(latest_price.price_close), Decimal(latest_price.fx_rate))
                if latest_price
                else None
            )
            metrics.append(
                self._metrics(
                    security,
                    trades,
                    events_by_security.get(security.id, []),
                    current_price_eur,
                    as_of=as_of,
                    income_basis=income_basis,
                    cost_basis=cost_basis,
                    costs_by_trade=costs_by_trade,
                )
            )

            position_eur = calculate_position_eur(trades)
            total_invested += position_eur.total_invested
            quantity = position_eur.quantity
            if quantity > 0:
                if current_price_eur is not None:
                    total_current_value += current_price_eur * quantity
                else:
                    total_current_value += position_eur.total_invested
                    fallback_securities.append(
                        PortfolioValuationFallback(
                            security_id=security.id,
                            ticker=security.ticker,
                            name=security.name,
                        )
                    )

        total_income = sum((m.total_income_received for m in metrics), Decimal("0"))
        total_realized = sum((m.realized_gain_loss for m in metrics), Decimal("0"))
        total_trade_costs = (
            sum(costs_by_trade.values(), Decimal(0)) if include_costs else Decimal(0)
        )
        total_recurring_costs = (
            sum((abs(Decimal(cost.amount_eur)) for cost in recurring_costs), Decimal(0))
            if include_costs
            else Decimal(0)
        )

        aggregate_total_return = None
        if total_invested > 0:
            aggregate_total_return = total_return(
                total_invested,
                total_current_value,
                net_dividends=total_income - total_trade_costs - total_recurring_costs,
            )

        period_days = self.investment_period_days(as_of=as_of)
        twr = self.portfolio_twr(
            net_of_costs=include_costs,
            income_basis=income_basis,
            costs_by_trade=costs_by_trade,
            recurring_costs=recurring_costs,
            as_of=as_of,
        )

        return PortfolioPerformance(
            total_invested=total_invested,
            total_current_value=total_current_value,
            total_return=aggregate_total_return,
            total_return_annualized=self._annualized(aggregate_total_return, period_days),
            time_weighted_return=twr,
            time_weighted_return_annualized=self._annualized(twr, period_days),
            money_weighted_return=self.portfolio_mwr(
                income_basis=income_basis,
                include_costs=include_costs,
                costs_by_trade=costs_by_trade,
                recurring_costs=recurring_costs,
                as_of=as_of,
            ),
            investment_period_days=period_days,
            total_realized_gain_loss=total_realized,
            total_income_received=total_income,
            by_security=metrics,
            metadata=self._metadata(
                income_basis=income_basis, cost_basis=cost_basis, portfolio=True
            ),
            portfolio_valuation=PortfolioValuationMetadata(
                cost_fallback_used=bool(fallback_securities),
                cost_fallback_securities=fallback_securities,
            ),
        )
