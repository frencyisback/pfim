# Security Detail

Open **Security detail** immediately below **Securities** in the sidebar.
Select a security by ticker and name. The list includes inactive securities
and securities without an open position. Use **Securities** to enter prices
or edit the catalogue.

## Security Record

The table shows the current values of the nine fields displayed in the
Securities register.

| Field | Display |
|---|---|
| Ticker | Security symbol |
| Name | Current catalogue name |
| ISIN | International Securities Identification Number |
| Type | Instrument type, including the legacy ETF type |
| Currency | Security quotation currency |
| Sector | Sector classification |
| Industry | Industry classification |
| Country | Country classification |
| Status | Active or Inactive |

An em dash marks an unfilled field. The quotation currency identifies the
security, while every price in the chart is in euros.

## Recorded Prices (EUR)

Each dot represents one saved unit price for this security. The chart reads
`price_close_eur`, the EUR equivalent fixed when the price was recorded.
This applies to all quotation currencies, including EUR. For example, a USD
price saved at an equivalent of €80 appears at €80 even if the exchange
rate changes later. [Currency conversion on entry](multi-currency.md)

The chart includes prices recorded on or before **today in the browser's
local calendar**. It refreshes the cutoff when the local date changes and
when the user returns to the page. Dots are spaced by elapsed calendar time.
Straight segments connect consecutive dots. Prices on June 1 and June 10
produce two dots joined by one segment. The dates in between have no
observations or tooltips. The line begins at the first quote and ends at
the last one.

Hover over a dot to see its date, exact stored EUR unit price (up to six
decimal places), and source. The source distinguishes manual entry, CSV
import, a price derived from a trade, and a historical trade price whose
original trade link is unavailable. Other source codes display as
**Unknown source**. A trade-derived price uses the quotation saved with
the operation.

| Situation | What the page shows |
|---|---|
| No selection | A prompt to choose a security |
| Empty catalogue | A message pointing to Securities |
| No prices, or only future prices | A message explaining that there are no recorded prices through today |
| One eligible observation | One dot, with its date and exact EUR price in the summary |
| Invalid date or invalid EUR price | A warning with the omitted count. Other eligible points remain visible |
| History request fails | An error alongside the selected security record |

A valid observation has a real calendar date and a positive EUR decimal in
the database's `NUMERIC(18,6)` range. Future-dated prices become eligible
on their recorded dates. [Unit prices and aggregate valuations](finance-calculations.md#61-observed-unit-prices-on-security-detail)

## Data and Backups

The page at `/security-detail` reads the catalogue from
`GET /api/v1/securities`. Selecting a security requests its full history
from `GET /api/v1/prices/{security_id}`. Requests use the security ID as
part of the cache key. Changing the selection cancels an outgoing request
for the previous security. Price entry, import, trade changes and a
successful restore invalidate the relevant cached data.

The page reads the existing SQLite schema. Previously eligible backups
remain restorable with their verified manifests and matching Alembic
revision. [Restore compatibility](data-safety.md#security-detail-compatibility)

## Regression Tests

- Date boundaries, sparse history and EUR decimal precision are covered by
  the [price history tests](../frontend/src/lib/securityPriceHistory.test.ts).
- The [chart tests](../frontend/src/components/securities/SecurityPriceHistoryChart.test.tsx)
  check the geometry of the segments across gaps and the single-dot display.
- Selection changes and cache refresh after edits or restore are covered
  by the [query tests](../frontend/src/api/priceHistory.test.ts).
- Read-only requests and the backup/restore cycle are exercised with a
  temporary SQLite database in the [API integration tests](../backend/tests/integration/test_security_detail_read_contract.py).
