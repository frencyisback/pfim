"""Pydantic schemas: report."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class PortfolioValuationFallback(BaseModel):
    security_id: int
    ticker: str
    name: str


class PortfolioValuationMetadata(BaseModel):
    """Identify the source of a portfolio valuation. Without a quote on or before the snapshot
    date, PFIM uses FIFO acquisition cost to keep the position in net worth. Clients must
    distinguish this estimate from market valuation.
    """

    price_policy: str = "latest_price_at_or_before_date_else_fifo_cost"
    cost_fallback_used: bool = False
    cost_fallback_securities: list[PortfolioValuationFallback] = Field(default_factory=list)


class NetWorthReport(BaseModel):
    as_of_date: dt.date
    total_accounts_balance: Decimal
    total_portfolio_value: Decimal
    net_worth: Decimal
    by_account: list[dict]
    # Cash and runway: sum checking accounts only (type=checking).
    liquid_balance: Decimal = Decimal("0")
    average_monthly_expenses: Decimal | None = None
    runway_months: Decimal | None = None
    portfolio_valuation: PortfolioValuationMetadata = Field(
        default_factory=PortfolioValuationMetadata
    )


class IncomeStatementPeriod(BaseModel):
    period_label: str  # e.g. "2026-07"
    total_income: Decimal
    total_expense: Decimal
    net: Decimal
    savings_rate_pct: Decimal | None


class IncomeStatementReport(BaseModel):
    period_from: dt.date | None
    period_to: dt.date | None
    periods: list[IncomeStatementPeriod]
    total_income: Decimal
    total_expense: Decimal
    net: Decimal
    # Average monthly rates with positive income, winsorized at P5/P95 as for average
    # spending. Exclude months without a rate from the sample.
    average_savings_rate_pct: Decimal | None = None
    savings_rate_months: int = 0


class CategoryAnalysisItem(BaseModel):
    category_id: int | None
    category_name: str
    total_amount: Decimal
    pct_of_total: Decimal


class CategoryAnalysisDetailItem(CategoryAnalysisItem):
    top_level_category_id: int | None


class CategoryAnalysisMonth(BaseModel):
    period_label: str  # e.g. "2026-07"
    total_amount: Decimal


class CategoryAnalysisReport(BaseModel):
    """Category analysis for expenses, income, and transfers with a shared structure and
    comparable statistics.
    """

    period_from: dt.date | None
    period_to: dt.date | None
    total_amount: Decimal
    # Complete aggregation at the top hierarchy level. Unlike by_category, this is not limited
    # to the top ten leaf categories.
    by_top_level_category: list[CategoryAnalysisItem]
    by_category: list[CategoryAnalysisItem]
    # All categories with direct transactions, without a top-ten limit. The root link allows
    # complete detail by hierarchy.
    by_category_detail: list[CategoryAnalysisDetailItem]
    by_month: list[CategoryAnalysisMonth]
    top_transactions: list[dict]


class AccountsBalanceHistoryPoint(BaseModel):
    """One net-worth history point. total_balance contains account cash only and decreases when
    cash buys securities. net_worth also includes the portfolio value on that date.
    """

    date: dt.date
    total_balance: Decimal
    portfolio_value: Decimal = Decimal("0")
    net_worth: Decimal = Decimal("0")
    portfolio_valuation: PortfolioValuationMetadata = Field(
        default_factory=PortfolioValuationMetadata
    )


class SecuritiesByType(BaseModel):
    type: str
    total_value: Decimal
    pct_of_total: Decimal
    positions_count: int


class SecurityPositionItem(BaseModel):
    security_id: int
    ticker: str
    name: str
    type: str
    sector: str | None
    industry: str | None
    country: str | None
    current_value: Decimal
    total_invested: Decimal
    unrealized_gain_loss: Decimal
    unrealized_gain_loss_pct: Decimal | None
    valuation_source: Literal["market_price", "fifo_cost"]


class PortfolioConcentration(BaseModel):
    """Portfolio concentration in a few holdings. effective_holdings is the inverse Herfindahl
    index, 1 / sum(w ** 2), and expresses the equivalent number of equally weighted holdings.
    """

    top_weight_pct: Decimal | None
    top_ticker: str | None
    top3_weight_pct: Decimal | None
    top5_weight_pct: Decimal | None
    effective_holdings: Decimal | None


class SecuritiesByCurrency(BaseModel):
    currency: str
    total_value: Decimal
    pct_of_total: Decimal
    positions_count: int


class SecuritiesByClassification(BaseModel):
    key: str
    total_value: Decimal
    pct_of_total: Decimal
    positions_count: int


class SecuritiesAnalysisReport(BaseModel):
    """Current portfolio analysis: open positions valued in EUR. Purchase and sale activity is
    available on the Securities page.
    """

    total_value: Decimal
    positions_count: int
    concentration: PortfolioConcentration
    by_type: list[SecuritiesByType]
    by_currency: list[SecuritiesByCurrency]
    by_sector: list[SecuritiesByClassification]
    by_industry: list[SecuritiesByClassification]
    by_country: list[SecuritiesByClassification]
    # Complete list of open positions. The rankings below remain limited to ten entries for
    # display.
    positions: list[SecurityPositionItem]
    top_by_value: list[SecurityPositionItem]
    top_gainers: list[SecurityPositionItem]
    top_losers: list[SecurityPositionItem]
    portfolio_valuation: PortfolioValuationMetadata = Field(
        default_factory=PortfolioValuationMetadata
    )


class DividendYearPoint(BaseModel):
    year: int
    gross: Decimal
    net: Decimal
    tax: Decimal
    cumulative_net: Decimal
    events_count: int
    growth_pct: Decimal | None  # Change from the previous year's net amount.


class DividendMonthPoint(BaseModel):
    """Seasonality: average receipts for each calendar month across the years in the period."""

    month: int
    net: Decimal
    events_count: int


class DividendBySecurity(BaseModel):
    security_id: int
    ticker: str
    name: str
    type: str
    gross: Decimal
    net: Decimal
    tax: Decimal
    events_count: int
    pct_of_total: Decimal
    yield_on_cost_pct: Decimal | None


class DividendByKey(BaseModel):
    """Breakdown by a key such as instrument type or event type."""

    key: str
    net: Decimal
    pct_of_total: Decimal
    events_count: int


class DividendsAnalysisReport(BaseModel):
    """Analysis of received coupons and dividends."""

    period_from: dt.date | None
    period_to: dt.date | None
    total_gross: Decimal
    total_net: Decimal
    total_tax: Decimal
    tax_incidence_pct: Decimal | None
    events_count: int
    first_event_date: dt.date | None
    last_event_date: dt.date | None
    trailing_12m_net: Decimal
    portfolio_yield_on_cost_pct: Decimal | None
    average_monthly_net: Decimal | None
    by_year: list[DividendYearPoint]
    by_month: list[DividendMonthPoint]
    by_security: list[DividendBySecurity]
    by_security_type: list[DividendByKey]
    by_event_type: list[DividendByKey]


class CostItem(BaseModel):
    """Individual cost item. is_estimated distinguishes rate-derived amounts from recorded
    amounts.
    """

    date: dt.date | None
    cost_type: str
    description: str
    amount_eur: Decimal
    is_estimated: bool
    ticker: str | None = None


class CostGroup(BaseModel):
    group: str  # taxes | trading | recurring
    total_eur: Decimal
    pct_of_total: Decimal
    estimated_eur: Decimal
    items: list[CostItem]


class RealizedResult(BaseModel):
    """Gross realized result for the period, used as the comparison basis for costs."""

    capital_gains: Decimal
    capital_losses: Decimal
    net_realized: Decimal
    income_gross: Decimal
    gross_result: Decimal


class FiscalPosition(BaseModel):
    """Tax position for the period, calculated centrally. Losses offset gains and tax applies to
    the net amount, ensuring reports share the same result.
    """

    capital_gains: Decimal
    capital_losses: Decimal
    # Gains minus losses: the taxable base.
    net_capital_gain_loss: Decimal
    tax_rate_pct: Decimal
    # Theoretical tax after offsetting, before deducting intermediary withholding.
    #
    gross_estimated_tax: Decimal
    # Capital gains taxes recorded as sale costs are actual withholdings, not estimates.
    #
    tax_already_withheld: Decimal
    # Estimated amount still due, never negative. Excess withholding is a credit that v1.0
    # does not model.
    estimated_tax_due: Decimal
    # Coupon and dividend withholdings, always actual amounts.
    dividend_withholding: Decimal


class CostImpact(BaseModel):
    pct_of_invested: Decimal | None
    pct_of_gross_result: Decimal | None
    annual_incidence_pct: Decimal | None
    # Period denominators exposed for verifiable percentages: daily averages including both
    # endpoints.
    average_invested_capital: Decimal | None
    average_portfolio_value: Decimal | None
    period_days: int | None
    twr_gross: Decimal | None
    twr_net: Decimal | None
    twr_drag_pct_points: Decimal | None


class CostsAnalysisReport(BaseModel):
    """Costs and taxes: financial-instrument expenses and their impact on performance."""

    period_from: dt.date | None
    period_to: dt.date | None
    realized: RealizedResult
    fiscal: FiscalPosition
    total_costs: Decimal
    total_estimated: Decimal
    groups: list[CostGroup]
    net_result: Decimal
    impact: CostImpact
    # Annual estimate as of today, separate from actual costs or taxes accrued during the
    # selected period.
    current_stamp_duty_estimate: CostItem | None = None
    disclaimer: str = (
        "Amounts marked as estimated use the configured tax rates, "
        "not tax documents. Check with a qualified professional "
        "before filing a tax return."
    )
