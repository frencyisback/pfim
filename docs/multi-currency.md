# Multiple currencies: conversion on entry

References: specification §9.8; code in `backend/app/finance/currency.py`
and `backend/app/utils/currency.py`.

## The rule in one sentence

> Every amount entering the system declares its **currency** and, unless
> it is in euros, the **exchange rate when the transaction occurred**.
> Its euro equivalent is calculated and saved immediately, once only.

Cash flows and costs are aggregated by summing persisted EUR equivalents.
For market prices, the authoritative source is instead the **native price
+ historical exchange rate** pair: valuations calculate their product
using all available `Decimal` precision, then multiply by quantity. In
neither case is a rate looked up on demand or replaced with the current rate.

## Why convert on entry rather than during calculation

**Numbers remain comparable.** Cash flow and portfolio data are different
datasets that contribute to the same indicators—net worth, income
statement, and cost analysis. If each converts independently, the same data
produces different totals depending on which component sums it. This was
the previous behavior: a foreign security's cost basis could be €1,800 in
one report and €1,780 in another because one reconverted at today's rate
while the other used the historical rate.

**Data does not change unexpectedly.** A purchase made at 0.90 USD/EUR cost
that amount. Converting at the current rate would rewrite history whenever
the page opened, and its cost basis would change without any user action.

**No missing values at runtime.** Looking up a rate during calculation
eventually means failing to find it—and having to choose between returning
an error and inventing a number. Previously, a foreign-currency transaction
without an available rate could be recorded but silently **generate no
cash transaction**, while the position appeared invested at its full value
but valued at zero, creating an invented loss equal to the entire investment.

## Rate convention

`fx_rate` expresses **how many euros one unit of the declared currency is worth**.

```
currency = "USD", fx_rate = 0.92   ->   100 USD is worth 92 EUR
```

This is the same direction as the `fx_rates` table (`from_currency` →
`to_currency = EUR`), so an archived rate can be used directly.

## System behavior

| Situation | Behavior |
|---|---|
| `currency` = EUR, no rate | Accepted, rate 1. The field is not shown in the interface. |
| `currency` = EUR, rate ≠ 1 | **Rejected (400)**: the euro has no exchange rate against itself; this is an input error. |
| `currency` ≠ EUR, rate present and > 0 | Accepted, equivalent frozen on the record. |
| `currency` ≠ EUR, rate missing | **Rejected (400)**, with a message identifying the currency and required input. |
| `currency` ≠ EUR, rate ≤ 0 | Rejected (422, schema constraint). |
| Amount, price, quantity, or equivalent `NUMERIC(18,6)` | Canonicalized to 6 decimals using `ROUND_HALF_EVEN`; **rejected before writing** if nonzero input would become zero or the absolute value exceeds `999999999`. |
| Rate `NUMERIC(18,8)` | Canonicalized to 8 decimals using `ROUND_HALF_EVEN`; must be positive and no greater than `9999999`. |
| Percentage or tax rate `NUMERIC(8,4)` | Canonicalized to 4 decimals using `ROUND_HALF_EVEN` before calculation and persistence; any stricter domain constraints still apply. |

The native value (`amount`, `price`, `total_amount`) **remains stored**
beside its converted value: it identifies the transaction on the broker
statement and is what the interface displays in detail rows. It is the
canonical value at 6 decimals; additional input digits are explicitly
rounded and do not constitute a second hidden “original” value.

## Where it applies

Every entity accepting an amount:

| Entity | Native fields | Euro fields |
|---|---|---|
| `transactions` | `amount`, `currency` | `fx_rate`, `amount_eur` |
| `trades` | `price` and `total_amount` in settlement currency; `quote_price` in security currency | `fx_rate`, `price_eur`, `total_eur` |
| `trade_costs` | `amount`, `currency` | `fx_rate`, `amount_eur` |
| `income_events` | `total_amount`, `tax_withheld`, `currency` | `fx_rate`, `total_eur`, `net_amount_eur` |
| `portfolio_costs` | `amount`, `currency` | `fx_rate`, `amount_eur` |
| `prices` | `price_close` (security currency) | `fx_rate`, `price_close_eur` |

**Every euro field is NOT NULL.** For amounts, costs, and cash equivalents,
this guarantee makes reports straightforward sums. The two EUR unit-price
fields are an exception when aggregating, as explained below.

Conversion canonicalizes and validates both the native value and the euro
result. Transactions, transfers, trades, income, and costs share this rule;
CSV preview and confirmation run the same validation. `NUMERIC(18,6)`
values use at most nine integer digits (`999999999`), and `NUMERIC(18,8)`
rates at most seven (`9999999`). These application limits are deliberately
more conservative than theoretical column capacity: on SQLite's `binary64`
path, they keep the last declared digit's round trip verifiable.

Canonical values are used **before** every derived calculation; results
are then brought back to column scale. Linked cash transactions are checked
again after aggregation—for example, `trade total + fees`—because two
individually valid values can overflow when combined. Nonzero input below
the supported scale cannot silently disappear as zero; an unrepresentable
**derived** remainder may become zero, such as a tax adjustment below
persistable precision.

`price_eur` and `price_close_eur` are informational unit representations at
6 decimals: useful for reading and compatibility, but not a basis to
multiply again by large quantities. For EUR FIFO cost,
`total_eur / quantity` is authoritative; for market valuation, `price_close`
and its frozen `fx_rate` are authoritative.

**Take care with `income_events.tax_withheld`**: it is the only native field
without a dedicated euro column. Its equivalent is
`total_eur − net_amount_eur`, consistent with the two actually persisted
equivalents, and must be derived that way—`ReportService.withholding_eur`
does exactly this. Multiplying `tax_withheld` by `fx_rate` again may differ
by one micro-euro at rounding boundaries and must not replace the accounting
difference between gross and net.

For that subtraction to represent withholding rather than an arbitrary
number, gross income and withholding must be **nonnegative**, and
withholding cannot exceed gross income: these are schema constraints, so
an out-of-range value returns 422. Without them, an input error could create
negative net income and a coupon could generate an **outgoing** cash
transaction categorized as “Coupons and Dividends.” The legitimate boundary
case—income entirely withheld at source, with zero net—remains allowed.

### Special cases

- **Accounts are euro-only.** An account balance is the sum of its already
  converted transactions: a dollar account would have a euro balance and
  a dollar opening balance, mixing two units in the same column. Record a
  foreign-currency transaction on a euro account by declaring currency and
  exchange rate **on the transaction**.
- **A trade's currency is its SETTLEMENT currency**, which may differ from
  the security's quote currency: a US security bought on a European market
  may settle in euros. Therefore, `trades.currency` is not constrained to
  `securities.currency`. `trades.price` remains the settlement unit price;
  `trades.quote_price` separately preserves the unit quote in security
  currency. The former generates the cash transaction and EUR equivalent;
  the latter feeds native FIFO and price history.
- **The quoted price follows three verifiable rules.** If settlement and
  security currencies match, `quote_price` may be omitted and is canonicalized
  to `price`; if supplied, it must match at stored precision. If currencies
  differ, `quote_price` is required. For a security quoted in EUR, it must
  also match `price_eur`, preventing two fields declaring the same value
  from silently diverging.
- **Trade invariants precede price history.** Quantity, `price_eur`,
  `total_amount`, `total_eur`, and the quote's implied exchange rate are
  validated before INSERT, including when a manual/imported price already
  exists on the same date and no automatic price needs to be created.
- **A price's currency is always the security's currency**: users do not
  choose it; they only declare the exchange rate. If quote and settlement
  share the same non-EUR currency, the trade-generated price retains the
  transaction's authoritative `fx_rate`. Only when the currencies differ
  is the quote's implied rate derived from `price_eur / quote_price`;
  the result is canonicalized to 8 decimals.
- **Valuations do not amplify a rounded EUR unit price**: current positions,
  summaries, performance, and history calculate
  `price_close × fx_rate × quantity`, retaining the unquantized unit
  product. `price_close_eur` remains exposed as information at 6 decimals,
  but does not replace the frozen native pair in totals.
- **A percentage cost inherits the transaction's currency and rate**:
  it is a fraction of that equivalent, and a different rate would create
  a fee inconsistent with the transaction it applies to. A fixed-amount
  cost declares its own currency and rate (a euro stamp-duty charge on a
  dollar transaction is a real-world example).
- **Transaction CSV import uses one rate for the whole file**, consistent
  with the profile's `default_currency`: a statement is by definition in
  a single currency.
- **Price CSV import** has an optional `fx_rate` column, required only for
  non-euro securities. Existing files continue working unchanged. A missing
  rate cell remains absent; it does not become an invented rate. Preview
  reports the error for foreign securities; if multiple valid rows concern
  the same security and date, it shows the price, rate, and equivalent
  from the last valid row, even on another page. A security's ticker and
  ISIN share the same key. Rules for invalid rows, partial imports, and
  counts are described in [CSV formats](csv-formats.md).

## What is no longer required

The `fx_rates` table and its import are **no longer needed for calculations**.
They remain a **supporting archive**: `GET /api/v1/fx-rates/suggest` proposes
the latest known rate not after a given date, and the interface uses it to
prefill the rate field. This is only a suggestion—the value the user
confirms when saving is authoritative. If the archive is empty, users
enter the rate manually.

Manage it under **Settings → Exchange rate archive**. Import results
identify rows and columns to correct through `row_errors`, retaining the
`errors` count per invalid row and saving valid rows in one commit. All
duplicate rows for a direction are rejected; a global error cancels the
entire request. The archive retains its own reciprocal policy, distinct
from the last-valid-row rule for prices.

## Reading the interface

In the Coupons/Dividends form, gross and withholding labels show the
currently selected currency, suggested by the security but editable.
Net income appears in that currency with a preview EUR equivalent; an
incomplete field or invalid rate does not generate a false zero net.
Example: gross 100 USD, withholding 10 USD, rate 0.90 → net 90 USD / 81 EUR.
Full withholding correctly produces zero net. The server remains
authoritative for validation, precision, and conversion when saving.

> **Display native amounts; sum euros.**

- **Detail rows** (transactions, trades, prices, coupons) show the declared
  amount alongside its equivalent: `$210.00 (€193.20)`.
- **Totals, KPIs, and charts** are always in euros only.
- Positions show two return percentages, and their difference is
  informative: the **euro** return is the actual experienced return
  (including exchange-rate effects); the **native** return isolates price movement.

In Security Analysis, aggregate percentages use EUR amounts and FIFO
costs. In Income Analysis, the **Last 12 months** KPI sums `net_amount_eur`
in the inclusive window from today minus 364 days through today,
independently of the table period. Its yield on cost uses the EUR FIFO cost
of positions open on the same date: future income and purchases do not
enter the KPI. Tables and totals retain the selected period, even when it
includes future events; the table's per-security return is labeled as
period return. Trailing KPIs remain visible even with an empty table.
With positive cost and no receipts, return is zero; without a positive
cost base it is not calculable (`null`, displayed as “—”).

## Migrating existing data

This section documents historical migrations already in the repository.
Changes A07–A20 neither introduce nor execute migrations or data cleanup.

Migration `d9f2a4c7e3b1` reconstructs missing equivalents in order of
reliability: EUR currency → rate 1; rate recoverable from the ratio between
an already saved equivalent and native amount → use that rate (the one
actually applied originally); foreign-currency prices → latest archived
`fx_rates` rate not after the price date. If none of these paths works,
it uses 1 and **prints a warning** identifying the securities for manual review.

The subsequent migration `d7b2e9f4a6c1` separates quoted and settlement
prices and introduces explicit ownership of trade-generated prices.
For legacy data, it can set `quote_price = price` only when the currencies
match. It therefore checks **before any DDL** and stops if it finds a legacy
cross-currency trade: that price cannot be reconstructed without a decision
about original data. Automatic prices attributable to a trade receive
`origin_trade_id`; historical prices without a verifiable owner are
preserved as `legacy_trade_orphan`, never implicitly deleted by a schema migration.
