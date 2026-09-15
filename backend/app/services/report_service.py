"""Service: ReportService."""

from __future__ import annotations

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.finance.income import yield_on_cost
from app.finance.periods import (
    DAYS_PER_MONTH,
    DAYS_PER_YEAR,
    trailing_year_start,
)
from app.finance.statistics import winsorized_mean
from app.repositories.account_repo import AccountRepository
from app.repositories.category_repo import CategoryRepository
from app.repositories.income_event_repo import IncomeEventRepository
from app.repositories.portfolio_cost_repo import PortfolioCostRepository
from app.repositories.price_repo import PriceRepository
from app.repositories.security_repo import SecurityRepository
from app.repositories.tax_event_repo import TaxEventRepository
from app.repositories.trade_repo import TradeRepository
from app.repositories.transaction_repo import TransactionRepository
from app.schemas.portfolio import PortfolioSummary
from app.schemas.report import (
    AccountsBalanceHistoryPoint,
    CategoryAnalysisDetailItem,
    CategoryAnalysisItem,
    CategoryAnalysisMonth,
    CategoryAnalysisReport,
    CostGroup,
    CostImpact,
    CostItem,
    CostsAnalysisReport,
    DividendByKey,
    DividendBySecurity,
    DividendMonthPoint,
    DividendsAnalysisReport,
    DividendYearPoint,
    FiscalPosition,
    IncomeStatementPeriod,
    IncomeStatementReport,
    NetWorthReport,
    PortfolioConcentration,
    PortfolioValuationFallback,
    PortfolioValuationMetadata,
    RealizedResult,
    SecuritiesAnalysisReport,
    SecuritiesByClassification,
    SecuritiesByCurrency,
    SecuritiesByType,
    SecurityPositionItem,
)
from app.services.account_service import AccountService
from app.services.performance_service import PerformanceService
from app.services.portfolio_cost_service import COST_TYPE_LABELS
from app.services.portfolio_service import PortfolioService
from app.services.tax_settings_service import TaxSettingsService
from app.utils.date_ranges import validate_date_range
from app.utils.errors import ValidationErrorPFIM

_CENT = Decimal("0.01")


def withholding_eur(event) -> Decimal:
    """Withholding on a coupon or dividend in EUR. tax_withheld uses the event's declared
    currency; total_eur and net_amount_eur are already converted. Their difference is the EUR
    withholding, consistent with net_amount_eur = (total_amount - tax_withheld) * fx_rate.
    """
    return Decimal(event.total_eur) - Decimal(event.net_amount_eur)


class ReportService:
    def __init__(self, db: Session):
        self.db = db
        self.account_repo = AccountRepository(db)
        self.category_repo = CategoryRepository(db)
        self.transaction_repo = TransactionRepository(db)
        self.tax_event_repo = TaxEventRepository(db)
        self.income_event_repo = IncomeEventRepository(db)
        self.portfolio_cost_repo = PortfolioCostRepository(db)
        self.price_repo = PriceRepository(db)
        self.security_repo = SecurityRepository(db)
        self.trade_repo = TradeRepository(db)
        self.account_service = AccountService(db)
        self.portfolio_service = PortfolioService(db)
        self.performance_service = PerformanceService(db)
        self.tax_settings_service = TaxSettingsService(db)
        # Request cache: the service lives only as long as its HTTP request, so it cannot serve
        # stale data.
        self._categories_cache: dict[int, object] | None = None
        self._portfolio_summary_cache: PortfolioSummary | None = None
        self._securities_cache: dict[int, object] | None = None

    def _securities_by_id(self) -> dict:
        """Cache complete security records within the request so reports can read tickers and
        types without a query per row.
        """
        if self._securities_cache is None:
            self._securities_cache = {s.id: s for s in self.security_repo.list()}
        return self._securities_cache

    def _portfolio_summary(self) -> PortfolioSummary:
        """Cache the portfolio summary once per request to avoid repeating trade and price reads."""
        if self._portfolio_summary_cache is None:
            self._portfolio_summary_cache = self.portfolio_service.get_summary()
        return self._portfolio_summary_cache

    def _portfolio_valuation_metadata(
        self, cost_fallback_security_ids: list[int]
    ) -> PortfolioValuationMetadata:
        securities = self._securities_by_id()
        fallbacks = [
            PortfolioValuationFallback(
                security_id=security_id,
                ticker=securities[security_id].ticker,
                name=securities[security_id].name,
            )
            for security_id in sorted(set(cost_fallback_security_ids))
        ]
        return PortfolioValuationMetadata(
            cost_fallback_used=bool(fallbacks),
            cost_fallback_securities=fallbacks,
        )

    def net_worth(self, as_of_date: dt.date | None = None) -> NetWorthReport:
        as_of_date = as_of_date or dt.date.today()
        if as_of_date > dt.date.today():
            raise ValidationErrorPFIM(
                "The net-worth date cannot be in the future",
                detail={"as_of_date": as_of_date.isoformat()},
            )

        # Historical snapshots use opened_on/closed_on, not current active status. Legacy NULL
        # values mean unknown endpoints and are included without inventing backfill dates.
        #
        accounts = self.account_repo.list(only_active=False, as_of_date=as_of_date)

        by_account = []
        total_accounts_balance = Decimal("0")
        liquid_balance = Decimal("0")
        for a in accounts:
            balance_info = self.account_service.get_balance(a.id, as_of_date=as_of_date)
            total_accounts_balance += balance_info.balance
            # Available cash sums checking accounts only. Savings and cash accounts remain part of
            # total net worth.
            if a.type == "checking":
                liquid_balance += balance_info.balance
            by_account.append(
                {"account_id": a.id, "name": a.name, "balance": str(balance_info.balance)}
            )

        portfolio_values, portfolio_fallbacks = (
            self.performance_service.portfolio_value_series_details(
                [as_of_date], include_same_day_trades=True
            )
        )
        total_portfolio_value = portfolio_values[as_of_date]

        avg_expenses = self._average_monthly_expenses(as_of_date)
        runway = (
            (liquid_balance / avg_expenses)
            if avg_expenses and avg_expenses > 0 and liquid_balance > 0
            else None
        )

        return NetWorthReport(
            as_of_date=as_of_date,
            total_accounts_balance=total_accounts_balance,
            total_portfolio_value=total_portfolio_value,
            net_worth=total_accounts_balance + total_portfolio_value,
            by_account=by_account,
            liquid_balance=liquid_balance,
            average_monthly_expenses=avg_expenses,
            runway_months=runway,
            portfolio_valuation=self._portfolio_valuation_metadata(portfolio_fallbacks[as_of_date]),
        )

    def _average_monthly_expenses(self, as_of_date: dt.date) -> Decimal | None:
        """Robust average expense over the latest twelve calendar months. Exclude transfers and
        security purchases, which do not reduce net worth. Sum signed amounts before
        converting each monthly net outflow into positive spending. Include empty months and
        winsorize monthly totals at P5/P95 before averaging. The current month ends at
        as_of_date. Return None when the robust average is not positive.
        """
        month_index = as_of_date.year * 12 + (as_of_date.month - 1) - 11
        start_year, zero_based_month = divmod(month_index, 12)
        start = dt.date(start_year, zero_based_month + 1, 1)
        items = self.transaction_repo.iter_filtered(date_from=start, date_to=as_of_date)
        expenses = self._economic_movements(self._filter_by_category_type(items, "expense"))

        monthly: dict[tuple[int, int], Decimal] = {}
        for offset in range(12):
            index = month_index + offset
            year, month = divmod(index, 12)
            monthly[(year, month + 1)] = Decimal("0")
        for transaction in expenses:
            key = (transaction.date.year, transaction.date.month)
            monthly[key] -= Decimal(transaction.amount_eur)

        average = winsorized_mean(list(monthly.values()))
        if average <= 0:
            return None
        return average

    def income_statement(
        self, date_from: dt.date | None = None, date_to: dt.date | None = None
    ) -> IncomeStatementReport:
        """Cash inflows and outflows, including security trades. Exclude both sides of
        own-account transfers. Linked trade movements already include costs, so adding trades
        or trade_costs again would double-count the same flow.
        """
        validate_date_range(date_from, date_to)
        items = self.transaction_repo.iter_filtered(date_from=date_from, date_to=date_to)

        by_month: dict[str, dict] = {}
        for t in items:
            if t.transfer_group_id is not None:
                continue
            key = t.date.strftime("%Y-%m")
            if key not in by_month:
                by_month[key] = {"income": Decimal("0"), "expense": Decimal("0")}
            # Use amount_eur: foreign-currency movements are already converted.
            amount = Decimal(t.amount_eur)
            if amount > 0:
                by_month[key]["income"] += amount
            else:
                by_month[key]["expense"] += amount

        periods = []
        for key in sorted(by_month.keys()):
            income = by_month[key]["income"]
            expense = by_month[key]["expense"]
            net = income + expense
            savings_rate = (net / income * 100) if income > 0 else None
            periods.append(
                IncomeStatementPeriod(
                    period_label=key,
                    total_income=income,
                    total_expense=expense,
                    net=net,
                    savings_rate_pct=savings_rate,
                )
            )

        total_income = sum((p.total_income for p in periods), Decimal("0"))
        total_expense = sum((p.total_expense for p in periods), Decimal("0"))
        savings_rates = [p.savings_rate_pct for p in periods if p.savings_rate_pct is not None]
        # Apply the same P5-P95 winsorization as average spending: retain every calculable month
        # and limit both tails without changing the original rates shown in monthly details.
        #
        average_savings_rate = winsorized_mean(savings_rates) if savings_rates else None

        return IncomeStatementReport(
            period_from=date_from,
            period_to=date_to,
            periods=periods,
            total_income=total_income,
            total_expense=total_expense,
            net=total_income + total_expense,
            average_savings_rate_pct=average_savings_rate,
            savings_rate_months=len(savings_rates),
        )

    def _categories_by_id(self) -> dict:
        """Cache complete categories once per request, including names and types needed by
        category reports.
        """
        if self._categories_cache is None:
            self._categories_cache = {c.id: c for c in self.category_repo.list()}
        return self._categories_cache

    @staticmethod
    def is_economic_movement(transaction) -> bool:
        """Determine whether a movement changes net worth. Exclude both sides of own-account
        transfers and security purchases/sales, which only change the form of assets. Include
        income payments and recurring costs. Category and runway reports use this definition;
        the cash flow statement also includes security trades.
        """
        return transaction.transfer_group_id is None and transaction.trade_id is None

    def _economic_movements(self, items) -> list:
        return [t for t in items if self.is_economic_movement(t)]

    def _filter_by_category_type(self, items, type_filter: str) -> list:
        """Select transactions by expense/income/transfer type. Use the category type when
        available, otherwise infer from the signed amount.
        """
        categories = self._categories_by_id()
        matched = []
        for t in items:
            category = categories.get(t.category_id) if t.category_id is not None else None
            category_type = category.type if category is not None else None
            if category_type is not None:
                if category_type == type_filter:
                    matched.append(t)
            elif type_filter == "expense" and Decimal(t.amount_eur) < 0:
                matched.append(t)
            elif type_filter == "income" and Decimal(t.amount_eur) > 0:
                matched.append(t)
        return matched

    def _category_analysis(
        self, type_filter: str, date_from: dt.date | None, date_to: dt.date | None
    ) -> CategoryAnalysisReport:
        """Shared expense, income, and transfer analysis by category. Sort by descending absolute
        amount so the first item is the largest regardless of sign.
        """
        validate_date_range(date_from, date_to)
        items = self.transaction_repo.iter_filtered(date_from=date_from, date_to=date_to)
        matched = self._filter_by_category_type(items, type_filter)

        if type_filter == "transfer":
            # Transfer analysis is the only one of these three analyses that includes transfers.
            #
            #
            # A transfer has two offsetting sides, so summing both would always display EUR 0.00
            # regardless of the amount moved. Count only the outgoing side in absolute value to
            # measure transferred volume.
            #
            #
            matched = [t for t in matched if Decimal(t.amount_eur) < 0]
            sign = Decimal("-1")
        else:
            matched = self._economic_movements(matched)
            sign = Decimal("1")

        by_category: dict[int | None, Decimal] = {}
        by_top_level_category: dict[int | None, Decimal] = {}
        by_month: dict[str, Decimal] = {}
        categories = self._categories_by_id()

        def top_level_id(category_id: int | None) -> int | None:
            if category_id is None:
                return None
            category = categories.get(category_id)
            if category is None:
                return None
            visited: set[int] = set()
            while category.parent_id is not None and category.id not in visited:
                visited.add(category.id)
                parent = categories.get(category.parent_id)
                if parent is None:
                    break
                category = parent
            return category.id

        for t in matched:
            amount = Decimal(t.amount_eur) * sign
            by_category[t.category_id] = by_category.get(t.category_id, Decimal("0")) + amount
            root_id = top_level_id(t.category_id)
            by_top_level_category[root_id] = (
                by_top_level_category.get(root_id, Decimal("0")) + amount
            )
            month_key = t.date.strftime("%Y-%m")
            by_month[month_key] = by_month.get(month_key, Decimal("0")) + amount

        total_amount = sum(by_category.values(), Decimal("0"))

        def category_rows(totals: dict[int | None, Decimal]) -> list[CategoryAnalysisItem]:
            rows = []
            for cat_id, total in totals.items():
                category = categories.get(cat_id) if cat_id is not None else None
                pct = (total / total_amount * 100) if total_amount != 0 else Decimal("0")
                rows.append(
                    CategoryAnalysisItem(
                        category_id=cat_id,
                        category_name=category.name if category else "Uncategorized",
                        total_amount=total,
                        pct_of_total=pct,
                    )
                )
            rows.sort(key=lambda row: abs(row.total_amount), reverse=True)
            return rows

        leaf_rows = category_rows(by_category)
        root_rows = category_rows(by_top_level_category)

        month_rows = [
            CategoryAnalysisMonth(period_label=key, total_amount=by_month[key])
            for key in sorted(by_month.keys())
        ]

        top_transactions = sorted(matched, key=lambda t: abs(Decimal(t.amount_eur)), reverse=True)[
            :10
        ]

        return CategoryAnalysisReport(
            period_from=date_from,
            period_to=date_to,
            total_amount=total_amount,
            by_top_level_category=root_rows,
            by_category=leaf_rows[:10],
            by_category_detail=[
                CategoryAnalysisDetailItem(
                    **row.model_dump(),
                    top_level_category_id=top_level_id(row.category_id),
                )
                for row in leaf_rows
            ],
            by_month=month_rows,
            top_transactions=[
                {
                    "id": t.id,
                    "date": t.date.isoformat(),
                    "description": t.description,
                    # Declared amount and EUR equivalent: for a foreign-currency movement, the first matches
                    # the user's statement; the second contributes to the total.
                    #
                    "amount": str(t.amount),
                    "currency": t.currency,
                    "amount_eur": str(t.amount_eur),
                }
                for t in top_transactions
            ],
        )

    def spending_analysis(
        self, date_from: dt.date | None = None, date_to: dt.date | None = None
    ) -> CategoryAnalysisReport:
        return self._category_analysis("expense", date_from, date_to)

    def income_analysis(
        self, date_from: dt.date | None = None, date_to: dt.date | None = None
    ) -> CategoryAnalysisReport:
        return self._category_analysis("income", date_from, date_to)

    def transfer_analysis(
        self, date_from: dt.date | None = None, date_to: dt.date | None = None
    ) -> CategoryAnalysisReport:
        return self._category_analysis("transfer", date_from, date_to)

    def securities_analysis(self) -> SecuritiesAnalysisReport:
        """Analyze current open portfolio positions; fully sold securities are excluded. Use each
        position's frozen EUR values without reconversion. Gain/loss percentages include
        currency effects and agree with the portfolio summary.
        """
        positions = self.portfolio_service.get_all_positions()

        items: list[SecurityPositionItem] = []
        by_type_value: dict[str, Decimal] = {}
        by_type_count: dict[str, int] = {}
        by_currency_value: dict[str, Decimal] = {}
        by_currency_count: dict[str, int] = {}
        classifications: dict[str, tuple[dict[str, Decimal], dict[str, int]]] = {
            "sector": ({}, {}),
            "industry": ({}, {}),
            "country": ({}, {}),
        }

        for p in positions:
            security = self._securities_by_id().get(p.security_id)
            value_eur = p.current_value_eur
            invested_eur = p.total_invested_eur

            type_key = security.type if security else "unknown"
            by_type_value[type_key] = by_type_value.get(type_key, Decimal("0")) + value_eur
            by_type_count[type_key] = by_type_count.get(type_key, 0) + 1

            by_currency_value[p.currency] = (
                by_currency_value.get(p.currency, Decimal("0")) + value_eur
            )
            by_currency_count[p.currency] = by_currency_count.get(p.currency, 0) + 1

            for field, (values, counts) in classifications.items():
                raw_value = getattr(security, field, None) if security else None
                key = raw_value.strip() if raw_value and raw_value.strip() else "Unspecified"
                values[key] = values.get(key, Decimal("0")) + value_eur
                counts[key] = counts.get(key, 0) + 1

            items.append(
                SecurityPositionItem(
                    security_id=p.security_id,
                    ticker=p.ticker,
                    name=p.name,
                    type=type_key,
                    sector=security.sector if security else None,
                    industry=security.industry if security else None,
                    country=security.country if security else None,
                    current_value=value_eur,
                    total_invested=invested_eur,
                    unrealized_gain_loss=value_eur - invested_eur,
                    unrealized_gain_loss_pct=p.unrealized_gain_loss_pct_eur,
                    valuation_source=p.valuation_source,
                )
            )

        total_value = sum(by_type_value.values(), Decimal("0"))
        by_type = sorted(
            (
                SecuritiesByType(
                    type=type_key,
                    total_value=value,
                    pct_of_total=(value / total_value * 100) if total_value != 0 else Decimal("0"),
                    positions_count=by_type_count[type_key],
                )
                for type_key, value in by_type_value.items()
            ),
            key=lambda r: r.total_value,
            reverse=True,
        )

        with_pct = [i for i in items if i.unrealized_gain_loss_pct is not None]
        gainers = sorted(with_pct, key=lambda i: i.unrealized_gain_loss_pct, reverse=True)
        losers = sorted(with_pct, key=lambda i: i.unrealized_gain_loss_pct)

        by_currency = sorted(
            (
                SecuritiesByCurrency(
                    currency=currency,
                    total_value=value,
                    pct_of_total=(value / total_value * 100) if total_value != 0 else Decimal("0"),
                    positions_count=by_currency_count[currency],
                )
                for currency, value in by_currency_value.items()
            ),
            key=lambda r: r.total_value,
            reverse=True,
        )

        def classification_rows(field: str) -> list[SecuritiesByClassification]:
            values, counts = classifications[field]
            return sorted(
                (
                    SecuritiesByClassification(
                        key=key,
                        total_value=value,
                        pct_of_total=(
                            value / total_value * 100 if total_value != 0 else Decimal("0")
                        ),
                        positions_count=counts[key],
                    )
                    for key, value in values.items()
                ),
                key=lambda row: row.total_value,
                reverse=True,
            )

        return SecuritiesAnalysisReport(
            total_value=total_value,
            positions_count=len(items),
            concentration=self._concentration(items, total_value),
            by_type=by_type,
            by_currency=by_currency,
            by_sector=classification_rows("sector"),
            by_industry=classification_rows("industry"),
            by_country=classification_rows("country"),
            positions=sorted(items, key=lambda i: i.current_value, reverse=True),
            top_by_value=sorted(items, key=lambda i: i.current_value, reverse=True)[:10],
            top_gainers=[i for i in gainers if i.unrealized_gain_loss_pct > 0][:10],
            top_losers=[i for i in losers if i.unrealized_gain_loss_pct < 0][:10],
            portfolio_valuation=self._portfolio_valuation_metadata(
                [p.security_id for p in positions if p.valuation_source == "fifo_cost"]
            ),
        )

    @staticmethod
    def _concentration(
        items: list[SecurityPositionItem], total_value: Decimal
    ) -> PortfolioConcentration:
        """Measure how strongly the portfolio depends on a small number of securities."""
        if not items or total_value <= 0:
            return PortfolioConcentration(
                top_weight_pct=None,
                top_ticker=None,
                top3_weight_pct=None,
                top5_weight_pct=None,
                effective_holdings=None,
            )

        ranked = sorted(items, key=lambda i: i.current_value, reverse=True)
        weights = [i.current_value / total_value for i in ranked]

        def cumulative(n: int) -> Decimal:
            return sum(weights[:n], Decimal("0")) * 100

        herfindahl = sum((w * w for w in weights), Decimal("0"))
        return PortfolioConcentration(
            top_weight_pct=weights[0] * 100,
            top_ticker=ranked[0].ticker,
            top3_weight_pct=cumulative(3),
            top5_weight_pct=cumulative(5),
            effective_holdings=(Decimal("1") / herfindahl) if herfindahl > 0 else None,
        )

    def accounts_balance_history(self) -> list[AccountsBalanceHistoryPoint]:
        """Point-in-time account and portfolio history through today. Include currently inactive
        accounts to preserve history. Include dates of cash movements, trades, and prices so
        market changes remain visible even without a bank movement.
        """
        today = dt.date.today()
        accounts = self.account_repo.list(only_active=False)
        per_account_points = {
            a.id: [
                point
                for point in self.account_service.get_balance_history(a.id)
                if point.date <= today
            ]
            for a in accounts
        }

        trades = [trade for trade in self.trade_repo.list() if trade.date <= today]
        traded_security_ids = {trade.security_id for trade in trades}
        prices = [
            price
            for price in self.price_repo.list_all()
            if price.date <= today and price.security_id in traded_security_ids
        ]
        all_dates = sorted(
            {point.date for points in per_account_points.values() for point in points}
            | {trade.date for trade in trades}
            | {price.date for price in prices}
        )
        if not all_dates and accounts:
            all_dates = [today]
        last_balance = {
            a.id: Decimal(a.opening_balance) if a.opened_on is None else Decimal("0")
            for a in accounts
        }
        cursor = {a.id: 0 for a in accounts}

        # Portfolio value completes each date's snapshot: buying securities reduces cash while
        # changing the form of wealth, without necessarily reducing net worth.
        #
        #
        # Calculate all dates in one pass. Separate queries for each date would greatly increase
        # query count and report runtime.
        #
        portfolio_values, portfolio_fallbacks = (
            self.performance_service.portfolio_value_series_details(
                all_dates, include_same_day_trades=True
            )
        )

        result = []
        for d in all_dates:
            total = Decimal("0")
            for a in accounts:
                points = per_account_points[a.id]
                while cursor[a.id] < len(points) and points[cursor[a.id]].date <= d:
                    last_balance[a.id] = points[cursor[a.id]].balance
                    cursor[a.id] += 1
                if (a.opened_on is None or a.opened_on <= d) and (
                    a.closed_on is None or a.closed_on >= d
                ):
                    total += last_balance[a.id]
            portfolio_value = portfolio_values[d]
            result.append(
                AccountsBalanceHistoryPoint(
                    date=d,
                    total_balance=total,
                    portfolio_value=portfolio_value,
                    net_worth=total + portfolio_value,
                    portfolio_valuation=self._portfolio_valuation_metadata(portfolio_fallbacks[d]),
                )
            )
        return result

    def dividends_analysis(
        self, date_from: dt.date | None = None, date_to: dt.date | None = None
    ) -> DividendsAnalysisReport:
        """Analyze collected coupons and dividends, their accumulation, paying securities, and
        annual distribution. Amounts are in EUR. Net income is the cash received after
        withholding; gross income is the issued amount. Their difference is the tax cost.
        """
        validate_date_range(date_from, date_to)
        as_of = dt.date.today()
        events = self.income_event_repo.list(date_from=date_from, date_to=date_to)
        trailing_events = self.income_event_repo.list(
            date_from=trailing_year_start(as_of), date_to=as_of
        )

        def net_of(e) -> Decimal:
            return Decimal(e.net_amount_eur)

        def gross_of(e) -> Decimal:
            return Decimal(e.total_eur)

        total_gross = sum((gross_of(e) for e in events), Decimal("0"))
        total_net = sum((net_of(e) for e in events), Decimal("0"))
        total_tax = total_gross - total_net

        # --- Annual totals, cumulative amounts, and year-on-year growth ---
        per_year: dict[int, dict] = {}
        for e in events:
            y = e.payment_date.year
            slot = per_year.setdefault(y, {"gross": Decimal("0"), "net": Decimal("0"), "count": 0})
            slot["gross"] += gross_of(e)
            slot["net"] += net_of(e)
            slot["count"] += 1

        by_year: list[DividendYearPoint] = []
        cumulative = Decimal("0")
        previous_net: Decimal | None = None
        for y in sorted(per_year):
            slot = per_year[y]
            cumulative += slot["net"]
            growth = (
                (slot["net"] - previous_net) / abs(previous_net) * 100
                if previous_net not in (None, Decimal("0"))
                else None
            )
            by_year.append(
                DividendYearPoint(
                    year=y,
                    gross=slot["gross"],
                    net=slot["net"],
                    tax=slot["gross"] - slot["net"],
                    cumulative_net=cumulative,
                    events_count=slot["count"],
                    growth_pct=growth,
                )
            )
            previous_net = slot["net"]

        # --- Monthly seasonality ---
        per_month: dict[int, dict] = {m: {"net": Decimal("0"), "count": 0} for m in range(1, 13)}
        for e in events:
            slot = per_month[e.payment_date.month]
            slot["net"] += net_of(e)
            slot["count"] += 1
        by_month = [
            DividendMonthPoint(month=m, net=per_month[m]["net"], events_count=per_month[m]["count"])
            for m in range(1, 13)
        ]

        # --- By security, with yield on cost ---
        per_security: dict[int, dict] = {}
        for e in events:
            slot = per_security.setdefault(
                e.security_id, {"gross": Decimal("0"), "net": Decimal("0"), "count": 0}
            )
            slot["gross"] += gross_of(e)
            slot["net"] += net_of(e)
            slot["count"] += 1

        positions = {
            p.security_id: p for p in self.portfolio_service.get_all_positions(as_of_date=as_of)
        }
        by_security: list[DividendBySecurity] = []
        for security_id, slot in per_security.items():
            security = self._securities_by_id().get(security_id)
            position = positions.get(security_id)
            # Yield on cost: net period income divided by current cost basis, meaningful only for
            # securities still held. Use the same function as /performance (§9.6) to keep both
            # endpoints consistent.
            #
            #
            yoc = None
            if position is not None and position.total_invested_eur > 0:
                yoc = yield_on_cost(slot["net"], position.total_invested_eur)
            by_security.append(
                DividendBySecurity(
                    security_id=security_id,
                    ticker=security.ticker if security else f"#{security_id}",
                    name=security.name if security else "",
                    type=security.type if security else "unknown",
                    gross=slot["gross"],
                    net=slot["net"],
                    tax=slot["gross"] - slot["net"],
                    events_count=slot["count"],
                    pct_of_total=(slot["net"] / total_net * 100) if total_net else Decimal("0"),
                    yield_on_cost_pct=yoc,
                )
            )
        by_security.sort(key=lambda r: r.net, reverse=True)

        # --- Breakdown by type ---
        def group_by(key_of) -> list[DividendByKey]:
            buckets: dict[str, dict] = {}
            for e in events:
                key = key_of(e)
                slot = buckets.setdefault(key, {"net": Decimal("0"), "count": 0})
                slot["net"] += net_of(e)
                slot["count"] += 1
            rows = [
                DividendByKey(
                    key=key,
                    net=slot["net"],
                    pct_of_total=(slot["net"] / total_net * 100) if total_net else Decimal("0"),
                    events_count=slot["count"],
                )
                for key, slot in buckets.items()
            ]
            rows.sort(key=lambda r: r.net, reverse=True)
            return rows

        def security_type_of(e) -> str:
            security = self._securities_by_id().get(e.security_id)
            return security.type if security else "unknown"

        # --- Summary indicators ---
        dates = [e.payment_date for e in events]
        # Dedicated inclusive window, independent of table filters.
        trailing_12m_net = sum((net_of(e) for e in trailing_events), Decimal("0"))
        total_invested = sum((p.total_invested_eur for p in positions.values()), Decimal("0"))
        portfolio_yoc = (
            yield_on_cost(trailing_12m_net, total_invested) if total_invested > 0 else None
        )

        average_monthly = None
        if dates:
            span_days = (max(dates) - min(dates)).days
            months = max(Decimal(span_days) / DAYS_PER_MONTH, Decimal("1"))
            average_monthly = total_net / months

        return DividendsAnalysisReport(
            period_from=date_from,
            period_to=date_to,
            total_gross=total_gross,
            total_net=total_net,
            total_tax=total_tax,
            tax_incidence_pct=(total_tax / total_gross * 100) if total_gross else None,
            events_count=len(events),
            first_event_date=min(dates) if dates else None,
            last_event_date=max(dates) if dates else None,
            trailing_12m_net=trailing_12m_net,
            portfolio_yield_on_cost_pct=portfolio_yoc,
            average_monthly_net=average_monthly,
            by_year=by_year,
            by_month=by_month,
            by_security=by_security,
            by_security_type=group_by(security_type_of),
            by_event_type=group_by(lambda e: e.event_type),
        )

    # Trade cost types representing taxes belong to the taxes group.
    #
    _TRADE_TAX_TYPES = {"tax", "stamp_duty", "capital_gains_tax"}
    # On a sale, these types represent capital gains tax already withheld and reduce the
    # estimate. Exclude stamp_duty, which taxes wealth rather than gains. The UI offers tax
    # for recording sale withholding.
    #
    #
    #
    _WITHHELD_CAPITAL_GAINS_TAX_TYPES = {"tax", "capital_gains_tax"}

    def fiscal_position(
        self, date_from: dt.date | None = None, date_to: dt.date | None = None
    ) -> FiscalPosition:
        """Period tax position: the single calculation of tax on net capital gains after
        offsetting losses. Deduct capital-gains tax already withheld and recorded as sale
        costs to avoid double-counting. Known v1.0 limits: offsets apply only within the
        queried period; there is no loss carryforward or distinction between tax income
        classes governing instrument eligibility in Italy. See docs/finance-calculations.md.
        """
        validate_date_range(date_from, date_to)
        tax_events = self.tax_event_repo.list(date_from=date_from, date_to=date_to)
        income_events = self.income_event_repo.list(date_from=date_from, date_to=date_to)
        trades = self._trades_in_period(date_from, date_to)
        return self._fiscal_position_from_data(
            tax_events=tax_events,
            income_events=income_events,
            trades=trades,
            costs_by_trade=self.trade_repo.costs_grouped_by_trade(),
        )

    def _fiscal_position_from_data(
        self,
        *,
        tax_events: list,
        income_events: list,
        trades: list,
        costs_by_trade: dict,
    ) -> FiscalPosition:
        """Build the tax position from already filtered collections, reusing cost/TWR data and
        the same time cutoff. Round compared tax amounts to cents with ROUND_HALF_UP while
        retaining source precision, so sub-half-cent residuals do not appear as outstanding
        tax.
        """

        capital_gains = sum(
            (
                Decimal(e.gross_amount)
                for e in tax_events
                if e.event_type == "capital_gain" and e.gross_amount
            ),
            Decimal("0"),
        )
        capital_losses = sum(
            (
                Decimal(e.gross_amount)
                for e in tax_events
                if e.event_type == "capital_loss" and e.gross_amount
            ),
            Decimal("0"),
        )
        net = capital_gains + capital_losses  # Capital losses are negative.

        rate = self.tax_settings_service.get_rate("capital_gains_tax_rate")
        gross_estimated = (
            (net * rate / 100).quantize(_CENT, rounding=ROUND_HALF_UP)
            if net > 0
            else Decimal("0.00")
        )

        already_withheld_raw = sum(
            (
                abs(Decimal(c.amount_eur))
                for t in trades
                if t.type == "sell"
                for c in costs_by_trade.get(t.id, [])
                if c.cost_type in self._WITHHELD_CAPITAL_GAINS_TAX_TYPES
            ),
            Decimal("0"),
        )
        already_withheld = already_withheld_raw.quantize(_CENT, rounding=ROUND_HALF_UP)
        estimated_due = max(
            (gross_estimated - already_withheld).quantize(_CENT, rounding=ROUND_HALF_UP),
            Decimal("0.00"),
        )

        return FiscalPosition(
            capital_gains=capital_gains,
            capital_losses=capital_losses,
            net_capital_gain_loss=net,
            tax_rate_pct=rate,
            gross_estimated_tax=gross_estimated,
            tax_already_withheld=already_withheld,
            estimated_tax_due=estimated_due,
            dividend_withholding=sum((withholding_eur(e) for e in income_events), Decimal("0")),
        )

    def _trades_in_period(self, date_from: dt.date | None, date_to: dt.date | None) -> list:
        return [
            t
            for t in self.trade_repo.list(date_to=date_to)
            if (date_from is None or t.date >= date_from) and (date_to is None or t.date <= date_to)
        ]

    def costs_analysis(
        self, date_from: dt.date | None = None, date_to: dt.date | None = None
    ) -> CostsAnalysisReport:
        """Cost and tax analysis. Compare realized gross results with taxes, operational charges
        and recurring costs. Capital-gains tax comes only from fiscal_position on offset net
        gains. All sections use the same effective cutoff, no later than today, exposed as
        period_to.
        """
        validate_date_range(date_from, date_to)
        today = dt.date.today()
        if date_from is not None and date_from > today:
            raise ValidationErrorPFIM(
                "The cost analysis start date cannot be in the future",
                detail={"date_from": date_from.isoformat()},
            )
        effective_to = min(date_to, today) if date_to is not None else today

        # Preload once. The same objects feed aggregates, tax position, asset bases, and both TWR
        # variants, reducing SQL cost and ensuring an identical temporal snapshot.
        #
        #
        all_trades = self.trade_repo.list(date_to=effective_to)
        all_income_events = self.income_event_repo.list(date_to=effective_to)
        all_recurring = self.portfolio_cost_repo.list(date_to=effective_to)
        all_prices = self.price_repo.list_all(date_to=effective_to)
        costs_by_trade = self.trade_repo.costs_grouped_by_trade()

        def in_period(value: dt.date) -> bool:
            return value <= effective_to and (date_from is None or value >= date_from)

        income_events = [event for event in all_income_events if in_period(event.payment_date)]
        trades = [trade for trade in all_trades if in_period(trade.date)]
        recurring = [cost for cost in all_recurring if in_period(cost.date)]
        tax_events = self.tax_event_repo.list(date_from=date_from, date_to=effective_to)
        fiscal = self._fiscal_position_from_data(
            tax_events=tax_events,
            income_events=income_events,
            trades=trades,
            costs_by_trade=costs_by_trade,
        )

        # --- Block 1: realized gross result ---
        income_gross = sum(
            (Decimal(e.total_eur) for e in income_events if e.total_eur is not None),
            Decimal("0"),
        )
        realized = RealizedResult(
            capital_gains=fiscal.capital_gains,
            capital_losses=fiscal.capital_losses,
            net_realized=fiscal.net_capital_gain_loss,
            income_gross=income_gross,
            gross_result=fiscal.net_capital_gain_loss + income_gross,
        )

        # --- Block 2: costs ---
        tax_items: list[CostItem] = []
        trading_items: list[CostItem] = []
        recurring_items: list[CostItem] = []

        # Recorded trade costs, with taxes separated from fees.
        securities = self._securities_by_id()
        for t in trades:
            security = securities.get(t.security_id)
            ticker = security.ticker if security else None
            for c in costs_by_trade.get(t.id, []):
                item = CostItem(
                    date=t.date,
                    cost_type=c.cost_type,
                    description=c.description or f"{c.cost_type} on {ticker or "trade"}",
                    amount_eur=abs(Decimal(c.amount_eur)),
                    is_estimated=False,
                    ticker=ticker,
                )
                if c.cost_type in self._TRADE_TAX_TYPES:
                    tax_items.append(item)
                else:
                    trading_items.append(item)

        # Capital gains tax: one entry after offsetting gains and losses. Prior withholding
        # appears above as an actual trade cost; only the remaining estimate belongs here.
        #
        if fiscal.estimated_tax_due > 0:
            compensation_note = (
                f" (capital gains {fiscal.capital_gains:.2f} offset by capital losses "
                f"{abs(fiscal.capital_losses):.2f})"
                if fiscal.capital_losses
                else ""
            )
            tax_items.append(
                CostItem(
                    date=None,
                    cost_type="capital_gains_tax",
                    description=(
                        f"Estimated capital-gains tax - {fiscal.tax_rate_pct:.2f}% "
                        f"of net {fiscal.net_capital_gain_loss:.2f}{compensation_note}"
                    ),
                    amount_eur=fiscal.estimated_tax_due,
                    is_estimated=True,
                )
            )

        # Coupon/dividend withholding: always actual recorded amounts.
        for e in income_events:
            if not e.tax_withheld:
                continue
            security = securities.get(e.security_id)
            tax_items.append(
                CostItem(
                    date=e.payment_date,
                    cost_type="withholding_tax",
                    description=f"Withholding on {security.ticker if security else "income"}",
                    amount_eur=abs(withholding_eur(e)),
                    is_estimated=False,
                    ticker=security.ticker if security else None,
                )
            )

        # Actual recorded recurring costs.
        for c in recurring:
            recurring_items.append(
                CostItem(
                    date=c.date,
                    cost_type=c.cost_type,
                    description=c.description or COST_TYPE_LABELS.get(c.cost_type, c.cost_type),
                    amount_eur=abs(Decimal(c.amount_eur)),
                    is_estimated=False,
                )
            )

        groups_raw = [
            ("taxes", tax_items),
            ("trading", trading_items),
            ("recurring", recurring_items),
        ]
        total_costs = sum((i.amount_eur for _, items in groups_raw for i in items), Decimal("0"))
        groups = [
            CostGroup(
                group=name,
                total_eur=sum((i.amount_eur for i in items), Decimal("0")),
                pct_of_total=(
                    sum((i.amount_eur for i in items), Decimal("0")) / total_costs * 100
                    if total_costs != 0
                    else Decimal("0")
                ),
                estimated_eur=sum((i.amount_eur for i in items if i.is_estimated), Decimal("0")),
                items=sorted(items, key=lambda i: i.amount_eur, reverse=True),
            )
            for name, items in groups_raw
        ]
        total_estimated = sum((g.estimated_eur for g in groups), Decimal("0"))

        activity_dates = (
            [trade.date for trade in trades]
            + [event.payment_date for event in income_events]
            + [cost.date for cost in recurring]
            + [event.event_date for event in tax_events]
        )
        effective_from = date_from or (min(activity_dates) if activity_dates else None)
        impact, end_portfolio_value = self._cost_impact(
            total_costs,
            realized,
            effective_from,
            effective_to,
            trades=all_trades,
            income_events=all_income_events,
            recurring_costs=all_recurring,
            costs_by_trade={
                trade_id: sum((Decimal(cost.amount_eur) for cost in costs), Decimal("0"))
                for trade_id, costs in costs_by_trade.items()
            },
            prices=all_prices,
        )

        # The current annual estimate is not a period cost, so exclude it from groups, totals, net
        # result, and cost ratios. Show it separately only if the period includes today and no
        # actual stamp duty exists for the current year.
        #
        includes_today = (date_from is None or date_from <= today) and (
            date_to is None or date_to >= today
        )
        current_year_stamp_exists = any(
            cost.cost_type == "stamp_duty" and cost.date.year == today.year
            for cost in all_recurring
        )
        current_stamp_duty_estimate = None
        if includes_today and not current_year_stamp_exists:
            estimated_stamp = self._estimated_stamp_duty(end_portfolio_value)
            if estimated_stamp > 0:
                current_stamp_duty_estimate = CostItem(
                    date=today,
                    cost_type="stamp_duty",
                    description=(
                        f"Current annual stamp duty estimate at {today.isoformat()} "
                        "(excluded from costs incurred during the period)"
                    ),
                    amount_eur=estimated_stamp,
                    is_estimated=True,
                )

        return CostsAnalysisReport(
            period_from=effective_from,
            period_to=effective_to,
            realized=realized,
            fiscal=fiscal,
            total_costs=total_costs,
            total_estimated=total_estimated,
            groups=groups,
            net_result=realized.gross_result - total_costs,
            impact=impact,
            current_stamp_duty_estimate=current_stamp_duty_estimate,
        )

    def _estimated_stamp_duty(self, portfolio_value: Decimal) -> Decimal:
        """Estimated current annual stamp duty: today's value times the configured rate, rounded
        to cents. Expose it separately from period costs because it is not yet an incurred
        charge.
        """
        rate = self.tax_settings_service.get_rate("stamp_duty_rate")
        return (portfolio_value * rate / 100).quantize(_CENT, rounding=ROUND_HALF_UP)

    def _cost_impact(
        self,
        total_costs: Decimal,
        realized: RealizedResult,
        period_start: dt.date | None,
        period_end: dt.date,
        *,
        trades: list,
        income_events: list,
        recurring_costs: list,
        costs_by_trade: dict[int, Decimal],
        prices: list,
    ) -> tuple[CostImpact, Decimal]:
        period_days = None
        average_invested = None
        average_portfolio_value = None
        end_portfolio_value = Decimal("0")

        if period_start is not None and period_start <= period_end:
            period_days = (period_end - period_start).days + 1

            # Value stays constant between successive trades/prices. Weighting these intervals yields
            # the daily period average without materializing thousands of dates.
            #
            change_dates = {period_start, period_end}
            change_dates.update(
                trade.date for trade in trades if period_start <= trade.date <= period_end
            )
            change_dates.update(
                price.date for price in prices if period_start <= price.date <= period_end
            )
            ordered_dates = sorted(change_dates)
            values, invested = self.performance_service.portfolio_value_and_invested_series(
                ordered_dates,
                include_same_day_trades=True,
                trades=trades,
                prices=prices,
            )
            weighted_value = Decimal("0")
            weighted_invested = Decimal("0")
            for index, date in enumerate(ordered_dates):
                next_date = (
                    ordered_dates[index + 1]
                    if index + 1 < len(ordered_dates)
                    else period_end + dt.timedelta(days=1)
                )
                weight = Decimal((next_date - date).days)
                weighted_value += values[date] * weight
                weighted_invested += invested[date] * weight
            average_portfolio_value = weighted_value / Decimal(period_days)
            average_invested = weighted_invested / Decimal(period_days)
            end_portfolio_value = values[period_end]

        pct_of_invested = (
            (total_costs / average_invested * 100)
            if average_invested is not None and average_invested > 0
            else None
        )
        pct_of_gross = (
            (total_costs / realized.gross_result * 100) if realized.gross_result > 0 else None
        )

        # Annual TER-style ratio: period costs divided by average daily value, then annualized
        # over the actual inclusive duration.
        annual_incidence = None
        if average_portfolio_value is not None and average_portfolio_value > 0 and period_days:
            incidence = total_costs / average_portfolio_value * 100
            annual_incidence = incidence * Decimal(DAYS_PER_YEAR) / Decimal(period_days)

        twr_gross, twr_net = self.performance_service.portfolio_twr_pair(
            period_start=period_start,
            as_of=period_end,
            trades=trades,
            income_events=income_events,
            recurring_costs=recurring_costs,
            costs_by_trade=costs_by_trade,
            prices=prices,
        )
        drag = (
            (twr_gross - twr_net) * 100 if twr_gross is not None and twr_net is not None else None
        )

        return (
            CostImpact(
                pct_of_invested=pct_of_invested,
                pct_of_gross_result=pct_of_gross,
                annual_incidence_pct=annual_incidence,
                average_invested_capital=average_invested,
                average_portfolio_value=average_portfolio_value,
                period_days=period_days,
                twr_gross=twr_gross,
                twr_net=twr_net,
                twr_drag_pct_points=drag,
            ),
            end_portfolio_value,
        )
