# Financial Calculations — Implementation Notes

The **reference formulas** are in the specification (§9). This document
explains **implementation choices**: what the code does when the formula
alone does not settle a decision, and when a value cannot be calculated.
Numerical examples are synthetic and illustrate calculation rules.

The entire engine lives in `backend/app/finance/` and is **pure**: it receives
numbers and lists and returns numbers. It knows nothing about SQLAlchemy or
HTTP and never reads the database. Its callers (services) are responsible for
providing resolved data. This separation makes it independently testable.

Amounts, quantities, FIFO and XIRR use `Decimal`. Annualizing cumulative
returns uses a `float` power, with finiteness checks and overflow handling:
an unrepresentable result makes only the affected annualized metric
unavailable (§2.4).
At the persistence boundary, `NUMERIC(18,6)` values — including amounts,
prices and quantities — are canonicalized to 6 decimal places, exchange
rates to 8, and percentages and tax rates to 4, always with `ROUND_HALF_EVEN`
**before** they are used in derived calculations. SQLite-safe application
limits are `999999999` for `NUMERIC(18,6)` and `9999999` for an exchange rate
stored as `NUMERIC(18,8)`: these are more conservative than the columns'
theoretical capacity so the last declared digit survives a round trip.
This technical normalization does not replace tax rounding to cents with
`ROUND_HALF_UP`, which applies only where the domain rule requires it.

Cash amounts used in aggregations arrive here **already in euros**: conversion
happens once, when the data enters the system
([multi-currency.md](multi-currency.md)). Market prices differ only in their
representation: the native price and historical exchange rate are frozen
together, and valuation calculates their `Decimal` product without looking
up a rate at runtime or prematurely quantizing the unit EUR price. The rule
lives in `finance/currency.py` as pure policy without access to rate tables.
The native FIFO view uses `quote_price`; the EUR view allocates the already
persisted `total_eur` over the quantity.

---

## 1. FIFO Position — `finance/portfolio.py`

Reference: specification §9.1, decision in [ADR/002](../ADR/002-fifo-vs-lifo.md).

Purchases form a chronological queue of **lots**. Each sale consumes lots
from the front: the oldest first.

```
realized_gain = Σ consumed_quantity × (sale_price − lot_unit_cost)
```

Sorting uses `(date, id)`: `id` breaks ties, so two operations on the same day
consume lots deterministically in the order in which they were recorded.

**Two ways to use the same algorithm.** `PositionTracker` maintains the lot
queue and updates it one operation at a time; `calculate_position` wraps it
by applying every trade and reading the final state. The incremental form
serves callers valuing **many consecutive dates** (net worth history and
TWR): it applies trades once in chronological order and reads the state
after each date, rather than rebuilding the queue every time. This is one
FIFO implementation used in two ways. Maintaining separate algorithms would
risk silent divergence between the numbers shown on different screens.

**Short selling is unsupported.** If a sale exceeds the quantity held on
that date, the function raises `ValueError`; `TradeService` translates it
into a **409**. The same check runs again before editing or deleting an
operation: deleting a purchase already consumed by a later sale would break
the chain and is therefore blocked.

**Availability by investment account (A03).** Cost-basis FIFO, P&L and the tax
register remain global by `security_id`. Before a new sale or deletion of a
purchase, the service also checks all running quantities for
`(account_id, security_id)` in `(date, id)` order, including future operations.
Units held in another investment account cannot cover a local sale. A new
trade follows existing trades on the same date. The first deficit produces
a 409 containing the investment account, security, date and quantity.

An already inconsistent history remains readable, without automatic cleanup.
The additional check blocks sales and purchase deletions for the affected
pair; purchases and sale deletions retain the existing guards because they
do not worsen availability. FIFO per investment account and transfers of
securities require a separate decision (ADR 002).

### The Variants and When to Use Them

| Function | Price used | When |
|---|---|---|
| `calculate_position` | Generic `price` field of the supplied object | Pure FIFO primitive and quantity checks |
| `calculate_position_native` | `trade.quote_price` (security currency) | Native cost and return of **one** position |
| `calculate_position_eur` | `trade.total_eur / trade.quantity` | **Any** aggregation across securities |

Adding the native `total_invested` of a EUR security to that of a USD security
produces a meaningless number. Every total, net worth calculation, tax
register and performance metric uses the EUR variant (specification §9.8).

`trade.price` is the price in the settlement currency: it may coincide with
the security currency, but that is not assumed. `trade.quote_price`,
`trade.price_eur` and `trade.total_eur` are frozen on the record when it is
created. EUR FIFO deliberately uses `total_eur / quantity`: `total_eur` is
the authoritative consideration that moved cash, whereas `price_eur` is an
informational unit field with 6 decimal places. Multiplying it back by large
quantities would amplify its rounding. See
[multi-currency.md](multi-currency.md): this is why the engine can remain pure and
never needs to consult an exchange-rate table.

---

## 2. Returns — `finance/returns.py`

### 2.1 Simple Return and Total Return

```
Simple return = (current EUR price − average open EUR cost) / average open EUR cost
Open-lot total return = (current value − open FIFO cost + attributable distributions − attributable costs) / open FIFO cost
```

Both raise `ValueError` if the denominator is zero.

**The reference capital is the position still open.** `starting_value` is the
cost of FIFO lots not yet sold, rather than the capital historically
invested: realized gains do not enter these two metrics. A security bought
and fully sold, even at a substantial profit, returns `null` for both and
has zero weight in the portfolio aggregate.

For each distribution, PFIM finds the units entitled to the payment in
the receiving investment account and the fraction of those units still
held today under FIFO. An ex-date uses the holding immediately before
that day's trades. When only the payment date is available PFIM uses its
closing holding. A declared payment quantity larger than the known holding
keeps the untracked portion out of open-lot performance. The recorded
payment amount remains intact in the cash ledger.

For example, 100 units costing €1,000 earn a €50 dividend. After 90 are
sold at an unchanged price, €5 belongs to the remaining €100 cost, for a
5% open-lot total return. A position closed and reopened begins with its
new units. Coupons, dividends and principal repayments all contribute their
attributable cash to total return. Principal repayments are reported
separately from coupon and dividend income.

With `cost_basis=include`, each remaining FIFO lot carries the same
fraction of the original purchase costs as of its original quantity.
Sale costs and portfolio-wide recurring fees enter the cash-flow measures
of their respective scopes. The aggregate uses the same open-lot numerator
and sums cost and value in EUR. The separate `total_income_received` field
is historical coupon and dividend income from funded holdings, including
holdings subsequently sold.

### 2.2 Time-Weighted Return (TWR)

Reference: §9.3. Measures portfolio return **with the timing and size of
capital contributions removed**: this is the figure comparable with a
market index.

History is split into subperiods bounded by external cash flows, and returns
are linked geometrically:

```
TWR = [(1+R₁) × (1+R₂) × … × (1+Rₙ)] − 1
```

Implementation choices not dictated by the formula:

- **The period starts with the first trade**, not the first cash flow.
  Flows also include coupons: income dated before the first purchase (a
  typo, or a position closed and repurchased) would open the period with an
  empty portfolio and zero initial capital, making TWR unavailable for the
  entire history. Earlier flows are discarded: they cannot have moved a
  portfolio that did not exist.
- Cash distributions enter TWR, XIRR and historical performance income
  once their account and security have a recorded purchase on or before
  payment. Payments on a security with no known investment remain visible
  in the income register. Returned principal is a dated cash flow in TWR
  and XIRR.
- **Income and costs also adjust the pre-flow value.** Coupons are a
  withdrawal to the cash account, but the immediately preceding value must
  include the receipt. Similarly, a cost included in return reduces that
  value. Adjusting only the flow would create fictitious capital in the next
  subperiod. For each day, let `P` be the value of securities before trades,
  `G` purchases minus sales, `I` income on the selected `gross`/`net` basis,
  and `C` included costs (zero when excluded):

  ```text
  flow = G - I + C
  pre_flow_value = P + I - C
  post_flow_value = P + G
  ```

  Adjustments are separate for each cost mode; flows on the same date are
  aggregated without inventing intraday times. With 100 already invested
  and an unchanged price, subsequent income of 10 yields 10%; a cost of 5
  on the income date makes the return 5%; a single cost of 10 after opening
  yields -10%. On separate dates, income of 10 followed by a cost of 5 links
  geometrically: `1.10 × 0.95 - 1 = 4.5%`.
- **Opening day.** When the period starts with the first trade, the initial
  flow remains excluded from subsequent linking. Given `V0`, the value of
  securities after the initial trades, the opening factor is
  `(V0 + I0) / (V0 + C0)`; subsequent periods start from `V0`. A purchase of
  100 with an initial commission of 5 therefore returns
  `100/105 - 1 = -4.7619%`; with initial income of 10 it returns
  `110/105 - 1 = 4.7619%`. The cost is not counted twice. If the selected
  period starts with an already open position, the basis is `P` instead,
  and that day's flows are included in the period. For an existing holding,
  this opening uses the latest quote through the selected first day. A
  price move on that day can therefore enter the euro result measured from
  the prior close and remain outside the report TWR.
- **A valuation immediately before every flow is required** to isolate the
  contribution's effect from actual return. If no imported price exists for
  that date, the position is valued at FIFO cost rather than ignored: on
  the purchase date the two coincide, and this is the only way to calculate
  TWR with sparse price histories.
- **When calculation is unavailable** (`None`): if a subperiod's opening
  capital is ≤ 0. This happens when a disposal exceeds the portfolio's value
  on that date, typically because the stored price predates the actual sale
  price. Returning a number would mean inventing one, so the value is
  declared unavailable. This also explains why trades fill days without a
  quote with an explicitly owned execution price (see §4 below).
  Closing the entire portfolio at the end of a day within the period,
  possibly followed by reopening, also retains `None`. Closing one security
  while others remain open does not reduce the portfolio to zero; a sale
  and repurchase on the same date remain aggregated at daily level.

The Costs and Taxation report also calculates a TWR using portfolio values
after estimated capital-gains tax. Its tax treatment and valuation requirements
are described in [Report TWR after costs](#report-twr-after-costs).

### 2.3 Money-Weighted Return (MWR / XIRR)

Reference: §9.4. Measures return on **capital as it was actually contributed**,
so timing affects it. Read it alongside TWR, not as its replacement.

```
0 = Σ CF_i / (1 + IRR)^(days_i / 365)
```

- Implemented through **bisection** over [−99.99%, +1000%], with tolerance
  `1e-7` and at most 200 iterations. `numpy_financial.irr` is not used because
  it assumes regular periods, incompatible with actual trade dates.
- Sign convention: invested capital is negative; disposals and ending value
  are positive.
- An individual open position needs a quoted terminal value. Its XIRR
  is unavailable when the final quote is missing, even if the prior
  receipts on their own yield a numerical root. A fully closed position's
  sales already provide its terminal proceeds. Portfolio XIRR follows the
  aggregate valuation policy, including the disclosed FIFO-cost fallback.
- **It is already an annual rate** and must not be annualized again. This is
  why the interface shows it only among annual values, never cumulative ones.
- Flows on the same date are summed in `Decimal`; totals exactly equal to
  zero are removed. At least two distinct remaining dates and totals with
  opposite signs are required. A purchase and identical valuation on the
  same day do not define an annual rate: the service returns `None`.
  Investing 100 and receiving 100 back after one year instead yields 0%.
- Returns `None` if an opposite-sign flow is missing, no meaningful time
  interval remains, or bisection finds no root in the interval. The primitive
  signals these cases with `ValueError`.

### 2.4 Annualization (CAGR)

Cumulative TWR uses the elapsed calendar days since the first trade. Its compound annual rate is

```text
annual_TWR = (1 + cumulative_TWR)^(365 / elapsed_days) − 1
```

This calculation requires positive elapsed time, a finite cumulative return above −100% and a representable result. For example, +1000% in a single day can produce an annual rate too large to represent. The cumulative TWR remains available.

**Annualized return on open FIFO lots.** Each remaining purchase has its own holding period. Group the remaining EUR acquisition cost by purchase date. For date `i`, let `C_i` be that residual cost and `d_i` the actual days from purchase to the valuation date. Find the common annual rate `r > −1` satisfying

```text
Σ C_i × (1 + r)^(d_i / 365) = quoted open value + attributable distributions − attributable purchase costs
```

The terminal amount uses the quoted market value of the open units in EUR, plus their share of dividends, coupons and principal repayments on the selected gross/net basis (§2.1). When costs are included, subtract the portion of each purchase cost belonging to its remaining units. The calculation treats those distributions and costs as adjustments to the terminal amount. TWR follows the portfolio through time. MWR/XIRR uses the dates and amounts of actual investor cash flows.

With **€100** of remaining cost from 730 days ago, **€100** from 365 days ago and a terminal amount of **€231**, the annual rate is **10%** because €100 × 1.10² + €100 × 1.10 = €231. The cumulative return is (€231 − €200) / €200 = **15.5%**. A single purchase date gives the ordinary CAGR over that holding period. A lot acquired on the valuation date contributes its cost at a growth factor of one.

The API returns the annual rate as a fraction (`0.10` for 10%). If `total_return_annualized` is null, `total_return_annualized_unavailable_reason` identifies the reason shown in the report.

| Reason | Interpretation |
|---|---|
| `no_open_cost` | No positive acquisition cost remains in open lots. |
| `no_elapsed_days` | All the remaining capital was invested on the valuation date. |
| `missing_quote` | An open security has no eligible price on or before the valuation date. A FIFO estimate may still be available for its valuation. |
| `undefined_rate` | The adjusted terminal amount gives no finite rate above −100%, or the rate cannot be represented numerically. With older lots present, the terminal amount must exceed the cost invested today. |

A valid flat result is **0%**. A dash and its explanation apply to the unavailable annualized figure.

---

## 3. Distribution Yield — `finance/income.py`

```
Yield on Cost = trailing coupon and dividend income attributable to open units / open EUR cost × 100
Current Yield = trailing coupon and dividend income attributable to open units / open EUR market value × 100
```

Both return a **percentage** (4.5 means 4.5%), not a fraction. "Last 12 months"
means the sum of income observed over **365 days, including today**, not a
projection of the nominal coupon. The Income report uses **net EUR income**;
Performance uses the selected `net`/`gross` basis, always in EUR. Comparing
the two views requires the same date and the same net basis.

**There is one window, defined in `finance/periods.trailing_year_start`.**
It contains exactly `DAYS_PER_YEAR` days in the inclusive interval
`[today − 364 days, today]`: today and today−364 are included; today−365 and
tomorrow are excluded. Sharing the boundary function, rather than only a
`365` constant, prevents `>=` and `>` comparisons from producing different
window lengths. Yield on Cost in `/performance/{id}`, `trailing_12m_net` in
`dividends-analysis` and `portfolio_yield_on_cost_pct` all use this boundary.
Average expenses in `net_worth` instead follow twelve **calendar months**, described
in §8, rather than a rolling 365-day window.

**Trailing metrics have their own window, independent of the report filter.**
`ReportService.dividends_analysis` captures one `as_of` date and loads income
from the last 365 days separately from income requested through
`date_from`/`date_to`. The denominator of `portfolio_yield_on_cost_pct` is the
EUR FIFO cost of positions open at that same `as_of`, therefore also excluding
future trades. Trailing KPIs remain visible when the table for the selected
period is empty. Tables and cash totals follow the selected period,
including future entries when requested. Period yield per security uses
the share of receipts paid through today in that period attributable to
units still held today, as in §2.1. The FIFO denominator is valued today.

The **monthly average** divides period coupon and dividend income by the
inclusive count of calendar months covered by the filter. An open start
begins at the first qualifying receipt. An open end runs through today
or the latest qualifying receipt if later. A single €120 dividend in a
January–December filter gives €10 per month. The annual table includes
zero-income years and compares consecutive calendar years. Growth on a
zero previous-year base is unavailable. Monthly seasonality sums all
selected years for each calendar month. The separate returned-capital
amount records principal repayments independently of income, yields
and growth.

YoC compares past distributions on surviving units with their cost.
Current yield compares those same distributions with today's valuation.
A positive denominator with zero attributable income yields 0%. A
missing quote leaves current yield unavailable.

---

## 4. Prices: Why a Trade Records One

The first trade for a security on a date without a quote stores its
`quote_price` in price history with `source="trade"` and
`origin_trade_id=<trade id>`. It **does not overwrite** an existing price
for that date: a manual or imported observation is more authoritative than
one execution.

The reason is TWR: without this price, valuation on a sale date would use an
older quote and could fall below the sale proceeds themselves — negative
opening capital, making TWR unavailable for the entire history.

A consequence to understand: if you never import quotes for a security,
its "current price" is the last price at which **you** traded it.

Ownership also makes deletion deterministic. Deleting a trade that does not
own the price changes nothing. Deleting the owner reassigns the price to the
first surviving trade on the same day and recalculates it from that trade's
data; if no replacement exists, the `ON DELETE CASCADE` foreign key deletes
only that automatic price. A manual entry or import on the same
`(security_id, date)` key replaces the automatic observation, clears
`origin_trade_id` and therefore survives subsequent trade deletion.

### 4.1 Point-in-Time Valuation and Declared Fallback

A snapshot on date `D` uses only trades and prices dated `<= D`: no future
quote can enter a historical value. For each security, it selects the most
recent available price no later than `D`.

When a price exists, EUR value follows one rule for both current snapshots
and historical series:

```text
market_value_eur = (price_close × fx_rate) × quantity
```

`price_close` and `fx_rate` are the authoritative native pair frozen on the
row. Their product is not first reduced to 6 decimal places, so a large
quantity does not amplify unit EUR price rounding. `price_close_eur` remains
persisted and exposed as an informational field with 6 decimal places, but
is not multiplied back to construct totals. This is not conversion at a
current exchange rate: the rate always comes from that same historical
price row.

If a position was already open but no usable price exists, PFIM neither
omits it nor invents a quote: it values it at the cost of the remaining open
FIFO lots. This is a **cost estimate**, not a market value. The report
contract exposes `portfolio_valuation` metadata for the current point and
every historical point, including `cost_fallback_used` and the affected
security IDs; Dashboard and Net Worth display the corresponding warning.
Entering a reliable historical quote removes the fallback from the date
when that quote becomes available.

### 4.2 Net Worth Composition by Account

The Net Worth snapshot adds `account_composition` for the tree in Reports.
`cash_accounts` contains checking, savings and cash balances;
`investment_accounts` contains the EUR value of each investment account's
holdings. Empty investment accounts appear with zero value. Both lists use
the snapshot's inclusive opening/closing dates, accept unknown legacy dates,
and are ordered by name and ID. Current active status is not a historical
filter. Cash associated with trading stays on its recorded reference account
and is counted once.

For each `(account_id, security_id)` pair, quantity is purchases minus sales
through the cutoff. With a quote, multiply that quantity by the latest
eligible `price_close × fx_rate`, using the same price rule as §4.1. A sale
on one account changes that account's quantity only. The calculation loads
trades, prices and account balances in batches rather than issuing one
valuation query per account.

FIFO cost and realised taxation remain global per security (§1). When a
quote is missing, allocate the security's global remaining FIFO cost to the
accounts in proportion to their remaining quantities. Each affected account
declares `cost_fallback_securities`; this is an **allocated cost estimate**,
not that account's historical acquisition cost or a market quote. For example,
if the global remaining cost is EUR 300 and accounts hold two units and one
unit, their estimates are EUR 200 and EUR 100.

Valuation and allocation use Decimal arithmetic. New account values are
reported in cents with reconciled rounding: the available account values
plus `unallocated_portfolio_value` sum to the aggregate portfolio value
rounded to cents. Aggregate valuation keeps its existing precision.

Inconsistent legacy records remain readable. Negative local quantities make
the affected visible account valuations unavailable (`value=null`). Holdings
on an account absent at the cutoff, or on a non-investment account, are not
assigned to a visible investment account. `issues` identifies the account,
security and reason. The unallocated amount reconciles the aggregate with the
values that can be shown, and the page reports issues even when that amount
is zero. Any legacy cash balance on an investment account is separately
declared in `unallocated_account_balance` and retained in Account balances.
No records are rewritten by this read-only report.

The original `by_account`, aggregate fields and net-worth CSV retain their
cash-balance contract; the CSV does not export the new holdings breakdown.
The database schema and backup format are unchanged.

---

## 5. Net Worth Projection — `finance/forecast.py`

Reference: §10. The specification does not unambiguously define every model
assumption, so they are fixed here and made explicit in the code:

- Starting net worth is split into **cash** and an **invested portfolio**,
  tracked separately. Only the portfolio generates returns: uninvested cash
  earns no interest in v1.0.
- With automatic savings (`monthly_savings_to_invest = null`), annual cash
  flow (income − expenses) is **fully invested** if positive; if negative,
  it is deducted from cash. An explicit monthly savings amount instead
  invests twelve times that amount and assigns the difference from annual
  cash flow to cash. The portfolio is not automatically sold to cover a
  deficit: the model assumes the user intervenes.
- `expected_annual_return` is a **total** return (price + dividends). The
  model does not distinguish "dividends distributed and not reinvested"
  because the input schema supplies no separate dividend yield.
- **Extraordinary contributions** (severance pay, unexpected expenses),
  positive or negative, are applied in full to the portfolio at the end of
  **(previous anniversary, current anniversary]**. The base date already
  represents starting net worth: contributions on or before it, and those
  beyond the horizon, are excluded. Each subsequent contribution within
  the horizon enters exactly once.
- Anniversaries preserve the base date's month and day, including the 29th,
  30th and 31st. February 29 becomes February 28 in nonleap years and returns
  to February 29 in the next leap year: every date is calculated from the
  original base date.
- Compounding is **annual**, not monthly: the year's savings are added to
  the portfolio as one end-of-period contribution. Extraordinary
  contributions are also added after the period's return, without
  intrayear returns.

For example, with a base date of June 1, 2026, the first year ends on
June 1, 2027: a contribution on September 1, 2026 and one on June 1, 2027 both
enter the first year; one on September 1, 2027 enters the second year if it
falls within the horizon.

The three curves (pessimistic / base / optimistic) differ **only** in the
return rate: all other inputs are identical, so their spread isolates the
return's effect.

### 5.1 Starting Net Worth and Saved Scenarios

`starting_net_worth` accepts only `auto` or a finite `Decimal`, including a
numeric string. Zero and negative values are allowed; arbitrary text, empty
strings, booleans, `NaN` and infinity are rejected. An explicit amount is
entirely initial cash. It can be used for a past, present or future base date.
For `auto`, the base date must be today or earlier. Starting cash uses the
Net Worth account lifecycle and EUR movement cutoff on that date. Starting
investments use trades and the latest available quotes through that same day,
including the ordinary FIFO cost fallback. Later activity cannot alter this
opening snapshot. A correction dated on or before the base date can.

Expand an entry in **Forecasts → Saved scenarios** to review its base date,
horizon, starting capital mode, monthly income and expenses, annual growth
rates, three annual return assumptions, monthly investment rule and any
dated contributions or withdrawals. Annual rates are stored as fractions
and displayed as percentages. Each dated entry has a label and a signed
EUR amount. A fixed monthly investment of €0 is an explicit choice to
keep savings in cash.

An unexecuted automatic start has a mode and base date. **Run** resolves
cash and investments on that date, then displays those two amounts and
their sum with the projection. With a manual start the specified amount
is cash and the opening investment value is €0. **Compare** displays
the assumptions and opening figures used for each selected scenario
alongside its base curve. This makes it possible to distinguish two
curves that differ in starting balances from two that differ in returns.

Monthly income and expenses are positive amounts or zero. Each annual
growth or return assumption must be at least −100%, and pessimistic ≤ base ≤
optimistic. Equal rates allow a single return assumption. A milestone already
met by opening cash plus investments has year index 0, even if net worth
falls below it during the first projection year.

Creation with invalid parameters returns 422 without inserting anything.
Before executing a saved scenario, `ForecastService` revalidates its
parameters with the same schema, before resolving net worth. An invalid
legacy record remains readable and produces a structured 400
`VALIDATION_ERROR`, with `scenario_id` and `fields`, without rewriting the
JSON. Additional historical properties tolerated by the schema remain in
the record and are ignored during calculation.

For a saved or restored record, omitted optional parameters use the same
defaults as a new API scenario. The starting mode defaults to automatic,
income and expense growth to 0%, monthly investment to automatic and
dated contributions to an empty list. Monthly income, monthly expenses
and the three return assumptions are required. Legacy dividend switches
have no effect because the model uses total returns.

Comparison validates all selected scenarios before executing any: if it
finds invalid parameters, it identifies the scenario preventing comparison
and does not present a partial result as complete. Listing scenarios and
using valid scenarios remain available.

### 5.2 Series Identity in Comparisons

Comparison shows each scenario's base curve. Chart data and lines use the
key `scenario_<id>`; the name is only a label. Duplicate names are
distinguished in the legend and tooltip by ID, for example
`Retirement (#12)`. Names such as `year` and `__proto__` also remain ordinary
labels without overwriting series. With different horizons, the shorter
curve ends at its own last forecast, without inserting artificial zeros or
truncating the longer one.

---

## 6. Cost of Aggregate Reads

**Single-date valuations.** The positions list, portfolio summary and Net
Worth snapshot request the latest eligible quote per security. The database
groups by security, finds its latest date at or before the cutoff and
returns those rows in one price query. These views load the trade history
through the cutoff to determine the remaining FIFO lots. The Securities
page likewise fetches its latest quotes in one `GET /prices/latest` request.

**Multi-date valuations.** `PerformanceService.portfolio_value_series`
uses a bulk trade read and a bulk historical price read for a nonempty set
of dates. Per-security cursors advance through those inputs in date order.
The query count is independent of the number of dates. Processing time also
depends on the number of dates, securities and open lots.
[`test_portfolio_value_series.py`](../backend/tests/integration/test_portfolio_value_series.py)
compares valuation results with a reference calculation and checks query counts.

The complete `/reports/net-worth/history` endpoint reads its accounts together.
One movement query supplies account IDs, dates and EUR amounts for all daily
balances. Trades and prices through today supply both the chart dates and
the valuations at those dates. The query count stays constant as accounts
are added, while the number of rows and daily values can grow.
[`test_point_in_time_reports.py`](../backend/tests/integration/test_point_in_time_reports.py)
checks the query budget and the cash and holdings values at each chart date.

**Performance and costs.** `/performance/portfolio` batches the trades,
income and prices used for its per-security metrics. Portfolio TWR and MWR
make additional aggregate reads. The costs report preloads trades, income,
recurring costs, trade costs and historical prices for its tax calculation,
average capital bases and TWR variants. The query-budget tests compare
the number of statements for two and ten securities on each endpoint.
[`test_performance_query_budget.py`](../backend/tests/integration/test_performance_query_budget.py)
and [`test_costs_period_coherence.py`](../backend/tests/integration/test_costs_period_coherence.py)
cover those comparisons.

### 6.1 Observed Unit Prices on Security Detail

Security detail reads one selected security's history in one request.
Each observation provides an EUR **unit price** in `price_close_eur`
at the six-decimal precision fixed on entry. Portfolio valuation uses
`price_close × fx_rate × quantity` before rounding the aggregate.

The price chart plots each recorded unit price against its calendar date
through local today. Straight lines connect successive points. Only dates
with an observation have a price marker or tooltip.
[Security detail guide](security-detail.md)

---

## 7. Capital Gains Tax — One Calculation

Reference: specification §11.4. This lives in
`ReportService.fiscal_position`, the **only** function that calculates it.

```
capital_gains − capital_losses = taxable_base
taxable_base × tax_rate = estimated_gross_tax
gross_tax − already_withheld = tax_still_due   (never negative)
```

Offsetting is significant: applying the tax rate to each gain individually
ignores losses entirely. For a synthetic gain of 1,000 and loss of 600 at a
26% configured rate, period-level offsetting gives an estimated tax of 104;
taxing the gain alone would give 260.

On an individual `tax_event`, `tax_amount` remains a **detail**: gross tax
on that gain before offsetting. It must never be summed across events, and
no total uses it. For automatic events it is rounded to cents with
`ROUND_HALF_UP` before persistence; `net_amount` subtracts exactly that
already rounded value, preventing SQLite from applying different implicit
rounding.

### 7.1 The Register Follows FIFO, Not Insertion Order

A sale's realized result depends on which lots were open **at that moment**.
Adding an earlier-dated purchase or deleting a previous sale changes the
lots consumed and therefore the taxable amount of every later sale.

For this reason, `TaxService.sync_capital_gain_events` is called after every
write affecting a security's trades — including purchases — and aligns
automatic events with recalculated FIFO. With two lots at different prices,
deleting the first sale can change the lot consumed by a later sale. Updating
that later sale's automatic event keeps its tax amount aligned with the
portfolio's recalculated realized result.

Ownership is not inferred from event type. `tax_events.origin` distinguishes:

- `automatic_trade`: FIFO-derived data owned by the synchronizer; ID and
  offsetting status persist, while date, type, amounts and description always
  follow the trade. It cannot be edited or deleted directly through the API;
- `manual`: user data of any type, potentially linked to a trade or income
  event; the synchronizer neither adopts nor rewrites it;
- `legacy_unknown`: a historical row whose origin cannot be reconstructed;
  when linked to an affected sale, it blocks automatic synchronization until
  explicitly resolved, preventing double counting or heuristic deletion.

An automatic sale that becomes a break-even sale loses its derived row.
Manual or legacy rows linked to a source instead block its deletion until
the user unlinks or explicitly handles them.

The interface also uses `origin`, without inferring it from links. Automatic
entries show that the originating trade manages them and remain protected.
Manual and legacy entries retain **Delete**; linked entries also offer
**Unlink source**, with explicit confirmation. Unlinking clears source
references while retaining the event and origin. Legacy entries are labeled
"Origin requires review"; an unexpected origin is reported as unrecognized
and does not enable direct actions.

Tax recorded as a `tax` or `capital_gains_tax` cost **on a sale** counts as
"already withheld". Stamp duty does not: it is a tax on assets.

---

## 8. Robust Average Monthly Expenses and Cash Runway

**Available cash** is the sum of EUR balances of `checking` accounts present
on the snapshot date. Negative checking-account balances are included.
Savings and cash balances also contribute to net worth. Investment accounts
contribute through their holdings under Portfolio value (§4.2). These amounts
do not enter the available cash figure. Any legacy investment-account cash
is retained separately in Account balances for reconciliation.

The snapshot considers the latest 12 **completed calendar months**, including the snapshot month only when the snapshot falls on its last day. For a snapshot on 15 August 2025, the baseline covers 1 August 2024 through 31 July 2025. August 2025 spending through the 15th is reported separately.

For each month with a recorded expense movement, PFIM sums signed EUR expense entries and reverses the sign once. Security purchase/sale settlements and transfers between owned accounts are excluded. A month without expense entries supplies no evidence of typical spending and is omitted. The number of eligible months is `n`. A month with expense entries can have zero net spending.

```text
P5, P95          = inclusive type-7 percentiles of the n monthly totals
average_expenses = Σ min(max(monthly_expenses, P5), P95) / n
cash_runway      = max(0, checking_balance) / average_expenses
```

`average_monthly_expenses` is null if the sample is empty or its mean is nonpositive. Positive checking balances require a positive baseline to produce runway. An exhausted or overdrawn checking balance gives zero months when a positive baseline or positive current partial-month spending provides evidence of spending. With neither, runway is null.

The JSON object `spending_coverage` provides inclusive `window_from`, `window_to`, `months_with_recorded_expenses` and `partial_month_spending` (null at month end). With €3,000 in checking and €1,000 in the one completed month with expense entries, runway is 3 months and the displayed coverage is 1/12. Months with entries can themselves be incompletely recorded. The estimate depends on the user’s data coverage.

---

## 9. Costs Aligned with the Period

`ReportService.costs_analysis` uses one effective inclusive interval for
realized results, taxes, costs and performance. `date_to` is capped at today
because a current metric cannot incorporate future rows; a future
`date_from` or an inverted interval is rejected. The response exposes the
**dates actually calculated**, not the requested dates when these extend
beyond today.

**Period costs** (`total_costs`) comprise recorded taxes, trading charges,
recurring costs and any estimated tax still due on the period's net realised
gains after sale withholding. A current annual stamp-duty estimate appears
separately when the interval includes today and no actual duty is recorded
on trades or recurring cost records for the current year. Withholding on
coupons and dividends and withholding on returned principal are reported
separately in the fiscal summary. The estimate of tax due on sales recognises
withholding recorded with the sale. Separately entered tax-register payments
do not settle that estimate. Only the period cost items are exported to CSV.

### Tax on unrealised gains

The JSON field `unrealized_tax` gives two estimates in EUR. The opening
snapshot values the positions held at the close of the day before the
interval. The closing snapshot values those held at the close of
`period_to`. An empty starting portfolio has a zero balance. The page
displays the closing snapshot in **Estimated tax on open positions**.

For each date, PFIM values the remaining FIFO quantity of each security
using the last recorded quote on or before that date and its stored EUR
exchange rate. It subtracts the remaining EUR FIFO cost, then sums gains
and losses across open securities. The estimated tax is the positive part
of this sum multiplied by the configured capital-gains rate, rounded to
cents (half up). Both dates use the same rate from Settings. This scenario
assumes a sale of all open positions at those prices. It excludes future
trading fees, offsets against realised losses and tax-loss carryforwards.
A missing quote on any open security makes that snapshot's monetary
figures unavailable. The report identifies the affected tickers. With no
open positions the net gain and estimated tax are both zero.

| Period measure | Calculation |
| --- | --- |
| Realised gross result | Realised gains + signed realised losses + gross coupon and dividend income |
| Unrealised gain/loss | Closing net unrealised gain/loss − opening net unrealised gain/loss |
| Gross result | Realised gross result + gross principal repaid + period change in unrealised gain/loss |
| Net realised result | Realised gross result − period costs |
| Change in estimated tax | Closing open-position tax estimate − opening estimate |
| Costs including tax change | Period costs + change in estimated tax |
| Relative to invested capital | 100 × costs including tax change / average daily FIFO invested capital |
| Relative to gross result | 100 × costs including tax change / gross result |
| Annual cost ratio (TER-like) | 100 × costs including tax change / average daily portfolio market value × 365 / days included |

The separate `realized.returned_capital_gross` field reconciles the cash side of a
principal repayment with the change in market value. For example, a holding worth
€100 that pays back €10 and then quotes at €90 has zero gross economic result
and no coupon income. PFIM retains the recorded acquisition cost in its tax model.

The three cost ratios require a positive denominator. The annual ratio
also requires a quoted value for all open holdings on each included day.
Averages weight each valuation by the number of days until the next change,
including the final day. The market value uses the latest quote available
by each date. The annual ratio includes estimated taxes and can be negative
when an earlier tax estimate falls. It measures the portfolio's annualised
cost incidence, including taxation.

For example, ten shares bought for €100 each and valued at €120 have an
unrealised gain of €200. At a configured rate of 26%, estimated tax is
€52. With no opening position and €4 in recorded fees, projected costs are
€56 and projected cost impact is 28% of €200. If all ten shares sell for
€120 the following period, the realised result includes the €200 gain and
the closing tax estimate falls to zero. Its €52 release offsets the €52
realised tax in that period's projection. With no further earnings or
costs, the gross economic result is zero and the percentage is unavailable.
A reserve release can also produce a negative projected cost amount.

The closing estimate creates no tax event. A missing opening or closing
quote suppresses the affected monetary change and ratios. Realised earnings,
period costs and the net realised result can still be calculated.

The report API supplies `unrealized_tax.unrealized_change_eur` for the
period change and `unrealized_tax.economic_gross_result_eur` for Gross result.
`realized.gross_result` is the realised subtotal. The displayed cost
percentages come from `impact.projected_pct_of_invested`,
`unrealized_tax.projected_cost_impact_pct` and `impact.projected_annual_incidence_pct`.
The quoted-value denominator is `impact.average_quoted_portfolio_value`.
Earlier fields such as `impact.pct_of_invested` describe cost incidence
on the original period-cost basis.

### Report TWR after costs

**TWR before costs** uses the portfolio's ordinary market valuation and
net coupon/dividend income. **TWR after costs** in this report is an
estimate. It uses the same income convention and accounts for recorded
fees, recurring charges and actual sale withholding. It also values the
portfolio after its estimated capital-gains liability at the start, at
cash flows and at the end. The liability consists of:

- Estimated tax on the positive net EUR gain of the remaining FIFO lots.
- Estimated tax on positive net gains already realised in the selected
  period through the valuation date, less capital-gains tax already
  withheld on sales, floored at zero. Applicable tax amounts are rounded
  to cents with `ROUND_HALF_UP`.

Selling a lot releases its open-position tax estimate. A recorded
withholding reduces sale proceeds and the outstanding realised estimate.
An unpaid estimate affects portfolio valuation. The only external flows
are those arising from recorded operations. When there is a portfolio at
the start of the filter, TWR uses its pre-trade holdings marked at the
opening day's available prices, consistent with §2.2. The separate
euro-denominated gain for the period uses the preceding day's close.

For example, with an initial €1,000 investment, a closing value of €1,200,
a 26% rate and no other flows or charges, before-cost TWR is 20%.
After €52 estimated tax, the closing valuation is €1,148 and estimated
after-cost TWR is 14.8%. **Return reduction** is **5.2 percentage points**
(before-cost TWR minus estimated after-cost TWR). With an unchanged price
in the following month, both returns and the change in tax are zero.

If half the shares are sold for €600 at that same price and €26 of tax is
withheld, realised gain is €100. The remaining open gain falls from €200 to
€100. The month therefore shows €0 Gross result and €74 Net realised result.
The €26 drop in estimated tax offsets the €26 withholding. The adjusted
cost for the month is zero, the share of Gross result is unavailable, and
estimated after-cost TWR is zero while the remaining shares stay invested.

The estimate requires quoted prices for the open holdings at its valuation
checkpoints and a positive capital base for each linked subperiod. A full
portfolio closure within the period follows the ordinary TWR availability
rule in §2.2. The page displays unavailable results as a dash. Portfolio
performance outside this report continues to use the standard return
bases described in §2.

If holdings remain and the final estimated net value is exactly zero, a
positive last subperiod opening can still yield a −100% return. A zero
base before another subperiod or a negative final net value makes the
estimate unavailable.

The API exposes the report-specific return in `impact.estimated_twr_net`
(fraction) and its signed difference from `impact.twr_gross` in
`impact.estimated_twr_drag_pct_points` (percentage points). The existing
`impact.twr_net` uses recorded costs. If the opening day's first quote
covers holdings that lacked a quote the day before, the TWR can have a
valid starting value while the period change in euro gains is unavailable.

## 10. Income Statement and Average Savings

`ReportService.income_statement` sums the period's transactions in EUR,
excluding only transfers between the user's own accounts. It therefore
includes transactions generated by securities trades: a purchase is an
outflow equal to gross consideration plus costs; a sale is proceeds net of
costs. The transaction's sign determines income or expense, even when costs
exceed proceeds. Trades, costs and tax gains/losses are not added again.

For each month with positive income:

```text
monthly_rate_pct = (income + signed_expenses) / income × 100
```

The sample includes only calculable monthly rates in the selected period:
months without income are excluded, and negative rates remain included.
Before averaging, `winsorized_mean` limits each rate to the sample's P5 and
P95 percentiles, calculated with inclusive **type 7** and linear
interpolation (`PERCENTILE.INC`, §8). With `n` calculable months:

```text
limited_rate_pct = min(max(monthly_rate_pct, P5), P95)
average_pct      = Σ limited_rates_pct / n
```

`average_savings_rate_pct` is the arithmetic mean of those limited rates,
and `savings_rate_months` is `n`. This is **winsorization**, not trimming: no
calculable month is removed and the denominator stays unchanged. Every month
has equal weight; this is not total balance divided by total income. With
no calculable months the mean is `null`; with one month it equals that
month's rate. A negative mean is valid and remains visible. The API value
is already a percentage, like `savings_rate_pct`, rather than a fraction to
multiply by 100 again. Monthly rates, income, expenses and income-statement
totals retain their original values: limiting affects only the mean.

### Economic household savings

The same response and its monthly rows also carry `economic_income`, `economic_spending`, `economic_savings` and `economic_savings_rate_pct`, in EUR and percentage points. The monthly CSV appends those columns. Household income includes ordinary income and dividends/coupons after withholding. Spending includes ordinary expense entries, recurring costs, recorded EUR trade fees on the trade date and any withholding charged on a return of capital. The full security purchase/sale amount, the principal returned and transfers between owned accounts are excluded. A sale whose fees consume all proceeds carries an expense even though its net cash entry is zero. Income analysis by category also excludes linked repayments of principal.

```text
economic_savings = economic_income − economic_spending
economic_savings_rate_pct = economic_savings / economic_income × 100
```

The period rate uses period totals, including expenses from months without income. An income denominator of zero or less yields null, while the savings amount and negative savings remain available. Example: €2,000 of salary, €1,000 of household spending and a €1,000 security purchase give zero net cash flow, €1,000 of household savings and a 50% economic savings rate. A €10 trade fee reduces household savings to €990.

Trade fees, recurring charges and investment distributions use their dated source records once, including legacy records with an unknown cash account. Only the corresponding bank movements enter the cash totals.

The Household savings panel in Net Worth shows the period's economic savings and rate alongside the historical average monthly cash surplus rate. Its dedicated filter starts with all history and applies to the panel. The snapshot and runway use their own dates.

Expense/income analysis and average expenses for cash runway continue to
exclude securities trades: their scope differs from the income statement.
Details by root use every category with direct transactions, without adding
parent totals again. Positive net expenses form the pie chart; zero or
refund categories remain in the sorted list. The Expenses export separates
summary and detail with `level`: summing both would count the same
transactions twice.

## 11. Known v1.0 Limitations

- **No multiyear capital-loss carryforward.** Offsetting applies only within
  the queried period; if the balance is negative, estimated tax is zero,
  but credit is not carried into later years as Italian rules would allow
  (through the fourth subsequent year).
- **No distinction between miscellaneous income and capital income.** In
  Italy, harmonized ETFs generate capital income that capital losses
  **cannot** offset, unlike shares. The model treats every gain/loss the
  same way, so estimates for a portfolio containing ETFs may be optimistic.
- **FIFO only.** No weighted average cost or LIFO
  ([ADR/002](../ADR/002-fifo-vs-lifo.md)).
- **No accrued coupon interest or yield curve** for bonds: `coupon_rate`,
  `coupon_freq`, `maturity_date` and `face_value` are master data and do not
  enter any calculation.
- Report amounts marked **estimated** (capital gains tax, stamp duty) derive
  from rates configured in Settings, not tax documents.
