# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Changed — average savings rate (September 12, 2026)

- The average savings rate now applies P5–P95 winsorization to calculable
  monthly rates, using inclusive type 7 percentiles (`PERCENTILE.INC`),
  before averaging. All calculable months remain in the sample without
  trimming; months without income are excluded and negative rates are allowed.
- The selected period is unchanged, with no mandatory 12-month window.
  Monthly rates, income, expenses, and income-statement totals retain their
  original values. The API contract and included-month count are unchanged.

Follow-up validation: **58 targeted backend tests and 2 frontend tests**
passed, along with TypeScript and static checks. Full-suite counts below
refer to the initial implementation.

### Changed — reports and interface usability (September 11, 2026)

- Removed the Minimum Y scale control and persisted monetary minimum from
  all charts: axes adapt to the data and retain negative values.
- Available cash and runway use checking accounts only; savings and cash
  accounts remain part of total account balances and net worth.
- The income statement and related Dashboard chart include security purchase
  and sale movements, already inclusive of costs, without duplication;
  internal transfers remain excluded. Expense/income analysis and average
  spending for runway retain their economic scope.
- Shared month selector with 1-month and 3-month shortcuts including the
  current month. Net Worth has a new average savings rate with an independent
  period and included-month count; the original arithmetic mean of unmodified
  rates was updated to P5–P95 in the September 12 follow-up.
- Expense analysis: detailed pie chart with root-category selection, all
  active descendant categories, and eight items per page sorted by spending.
  Direct root movements are included without duplication; complete CSV with
  root references supplements the top-level summary.
- Forecasts: numeric fields start empty with descriptive hints and explicit
  validation of required values. Account form fields have consistent heights.

API contracts extended without database schema changes.
Initial September 12 validation, before the P5–P95 follow-up:
**830 backend tests and 169 frontend tests** passed, along with lint and
build checks; browser testing used synthetic data.

### Fixed — September 7 audit, P2 priorities (September 11, 2026)

- **A07:** tax register driven by `origin`, with consistent manual/legacy
  actions and explicit source unlinking; automatic-entry protection retained.
- **A08, A10, A18:** security deactivation checked per investment account as
  of today and against future events; consistent create/update constraints
  without restricting legacy reads; frozen cash references included among
  account blockers.
- **A09:** one category-name resolution using `strip().casefold()`, explicit
  collisions, and composite-operation rollback without data cleanup.
- **A11–A12:** controlled CSV cell/header errors, per-row/column FX diagnostics,
  and price preview consistent with the last valid row of the whole file,
  including across pages and ticker/ISIN aliases.
- **A13:** income KPIs over 365 days through today, independent of the selected
  period and visible with an empty table; FIFO cost at the same cutoff.
  Security Analysis percentage documentation corrected to use the EUR basis.
- **A14–A16:** contributions assigned to anniversary intervals, correct leap
  years, charts identified by IDs, and parameter validation before execution,
  including saved scenarios.
- **A17:** unrepresentable annualizations set only the affected metric to
  `null`, preserving the report and the formula for ordinary cases.
- **A19–A20:** invalid manifests isolated and explained in the catalog;
  configurable SQLite copy-cycle limit with `BACKUP_TIMEOUT`, staging cleanup,
  and pre-restore failure before database exchange.

No changes to operational databases, existing backups, models, or migrations.
Functional and operational documentation, ADRs, and the risk register aligned.
Full suites: **824 backend tests and 158 frontend tests passed**; Black,
isort, Ruff, TypeScript, ESLint, and Vite build passed.
**A01–A20 resolved in the repository.**

### Fixed — September 7 audit, P1 priorities (September 8, 2026)

- **A01:** CORS covers security and maintenance middleware errors, enabling
  automatic capability renewal. Tests verify one retry and no repeat on
  network or maintenance failures, with Host/Origin checks still enforced.
- **A02:** CSV preview, pagination, and confirmation share immutable file and
  parameters; edits and navigation invalidate preview, stale responses are
  ignored, and duplicate confirmations are blocked synchronously.
- **A03:** selling and purchase deletion validate running quantities per
  investment account/security, including future dates, before writes. Global
  FIFO, costs, P&L, and taxes retain their scope.
- **A04:** income and costs adjust TWR pre-flow value as well as flows;
  opening factors and calculations with/without costs are consistent. Periods
  ending a day with the entire portfolio emptied remain unavailable, even
  if followed by reopening.
- **A05:** XIRR aggregates flows by date and removes exactly zero totals;
  two remaining dates and opposite signs are required, preventing arbitrary
  rates for movements that cancel on the same day.
- **A06:** the income form shows the actual currency for gross income and
  withholding, and separates native and EUR net amounts without treating
  incomplete inputs as zero.

No changes to operational databases, existing backups, schema, or migrations.
Functional documentation, ADR 002, and the risk register aligned. A07–A20
were still open on September 8; their subsequent completion is described above.
Full validation: **678 backend tests and 133 frontend tests passed**, along
with Black, isort, Ruff, TypeScript, ESLint, and the Vite build.

### Fixed — general consistency, completeness, and efficiency review

- Trades distinguish settlement price (`price`, with `currency`) from the
  quote in the security's currency (`quote_price`). Native FIFO and automatic
  prices use the latter; cash, converted values, and EUR aggregates use the
  former. Ambiguous or inconsistent combinations are rejected.
- Derived prices declare their owner through `origin_trade_id`: deletion
  reassigns or removes only automatic data, while a manual/imported price
  becomes authoritative, clears automatic ownership, and survives. Migration
  `d7b2e9f4a6c1` fails before DDL if legacy currencies prevent quote-price
  backfill, links only unique matches, and retains orphans as
  `legacy_trade_orphan`.
- Open unquoted positions are no longer omitted from Portfolio, its summary,
  Security Analysis, or aggregate performance: they use FIFO cost with
  explicit metadata and warnings. Metrics requiring an actual price remain
  unavailable.
- Costs and Tax uses one effective period for costs, taxes, bases, and TWR;
  percentages and annual incidence use daily average invested capital and
  portfolio value. Current stamp duty is informational and separate from
  incurred costs; tax amounts are settled to the cent.
- All list/report intervals reject `date_from > date_to`. Empty CSV exports
  retain headers, and the Securities export includes every open position,
  keeping the Top 10 limit only for summary rankings.
- Removed N+1 queries from latest-price reads and the costs report; query
  count does not grow with the number of securities. Cash Flow text sorting
  is natural even across pages (`Instalment 1`, `Instalment 2`, `Instalment 10`).
- The frontend reports query errors, corrects the page after deletion,
  exposes `aria-sort` on headers, and lazily loads route pages. Price preview
  ignores stale responses after file changes, and batch imports invalidate
  reports/performance. Quote age uses calendar days. The trade table
  distinguishes settlement and quoted prices.
- Latest-price endpoints apply today's cutoff, like net-worth views: future
  preparatory data stays in history but is not presented as current quotes.
- The test dependency changed to `httpx2`, compatible with Starlette 1.3;
  Windows constraints and the hashed lock were regenerated. The Ruff
  contract is now explicit and stable across versions.
- Writers canonicalize `NUMERIC(18,6)` values, `NUMERIC(18,8)` exchange rates,
  and `NUMERIC(8,4)` percentages with `ROUND_HALF_EVEN` before calculations
  and persistence. SQLite-safe absolute application limits are 999,999,999,
  9,999,999, and 9,999 respectively; rates remain strictly positive. Nonzero
  inputs that would become zero are rejected, while broader DDL is retained
  for compatibility.
- Normalization covers manual entries, transfers, CSV, trades and linked
  movements, `opening_balance`, income, costs, prices, numeric bond metadata,
  and tax events. Cost percentages are rounded to four decimals before
  calculating and freezing the amount, so `percentage_used` matches the
  value actually applied.
- EUR FIFO allocates `total_eur / quantity`, matching lot consumption to cash
  value without multiplying back a rounded unit price. Market valuations
  likewise use `price_close × fx_rate` before quantity; `price_eur` and
  `price_close_eur` remain verifiable unit representations.
- Price-import preview and confirmation share error precedence: structural
  and numeric fields, including malformed exchange rates, are validated
  before ignoring an unknown ticker, producing consistent counts.
- Configurable tax rates are canonicalized to four decimals and limited to
  0–100%. Manual tax events normalize every numeric field and require
  nonnegative gross amounts for `capital_gain` and nonpositive amounts for
  `capital_loss`, leaving other types editable. Automatic taxes retain
  separate cent rounding with `ROUND_HALF_UP`; differences below persistable
  scale do not generate an event.

### Added — clearer reports and summary portfolio classifications

- Each Report tab exposes only its own CSV export and reuses its displayed
  period. Periodic reports select whole months or years; point-in-time
  snapshots remain separate. Costs and Tax opens on the full history.
- Expense Analysis exposes the complete top-level category breakdown,
  separate from the Top 10 leaf categories; CSV distinguishes both sets with
  `level=top_level|leaf`.
- Net-worth snapshot average monthly spending uses 12 calendar months,
  including zeros, with P5–P95 winsorization (`PERCENTILE.INC`); no month is
  removed, and other series or averages are unchanged.
- The Dashboard Income/Expenses chart explicitly states that it aggregates
  all accounts and excludes transfers and security trades.
- Securities have three optional scalar labels: sector, industry, and
  country, editable in the catalog and aggregated over open positions. For
  ETFs, these describe the security rather than weighted underlying exposure.
- Reversible migration `c3f8a1d6e4b2` adds nullable `securities.industry`,
  preserving existing rows, sector, and country.

### Changed — sortable, compact tables and shared column-chart scale

- Persistent tables start collapsed except Cash Flow and Portfolio;
  import previews remain open and in original order.
- Informational columns have two sorting states, stable/natural order, and
  missing values always last. Cash Flow includes Description, account and
  category names, and EUR value.
- Monetary column charts share a minimum upper Y bound of EUR 10,000,
  expand with the data, and offer a global preference persisted locally.

### Security — opt-in, crash-safe SQLite restore with offline recovery

- Restore remains disabled by default and explicitly requires
  `RESTORE_ENABLED=true`, enabled backups, and the build's exact Alembic
  revision. It neither runs migrations nor accepts legacy or other-revision
  backups.
- The HTTP path uses a maintenance gate that rejects new requests and waits
  for active ones. Separate OS locks protect the backend lifetime and
  serialize backup, restore, recovery, and the offline CLI.
- Modern candidates are checked for manifest, header, integrity, foreign
  keys, confirmed SHA-256, absent sidecars, and revision. Before swapping,
  a new verified self-contained backup is created; staging stays on the
  same filesystem.
- Durable journal `.pfim-restore.json` records `prepared`, `live_moved`, and
  `committed`: recovery rolls back before commit and rolls forward after it,
  under lock and before the startup schema guard. Recovery can resume after
  a second crash; post-commit corruption fails closed without implicit rollback.
- Each operation has an idempotent `request_id` and a status record accessible
  through `/backup/restore-operations/{request_id}`; confirmation and hash
  prevent restoring a different file from the one approved.
- Added `scripts/restore.ps1` for offline maintenance while the backend is
  stopped. It uses the API's protocol, refuses to start while Uvicorn holds
  the instance lock, and recovers a pending journal before the schema guard.
  A new restore still requires a verifiable live database and mandatory
  pre-restore backup.
- Dedicated tests cover gates, locks, eligibility, idempotency, CLI, SQLite
  sidecars, fault injection, and real process termination at commit points
  using temporary databases. ADR 006 defines the architectural criteria.

### Robustness — block startup on incompatible Alembic schemas

- Before accepting requests, FastAPI lifespan compares the exact set of
  heads shipped in `backend/migrations` with the configured database's
  current heads.
- Missing, unversioned, older, newer, or differently branched databases stop
  startup with an error reporting expected and found revisions. Health checks
  cannot report a process healthy while connected to an incompatible schema.
- The check uses no `upgrade`, `stamp`, `create_all`, or other mutating
  fallback. File-backed SQLite is inspected through a separate `mode=ro`
  connection; a missing path is not created.
- Tests cover mismatches and exact matches, including lifespan, in-memory
  databases, absence of Alembic upgrade calls, and preservation of the
  rejected file's hash, timestamp, and sidecars.
- Updated `backend/migrations/README`, which still described placeholder
  schemas and migrations, to the actual Alembic chain and operating procedure.

### Changed — price history retains only fields PFIM uses

- Removed `price_open`, `price_high`, `price_low`, and `volume` from the model,
  API contract, repository, import, and frontend.
- Supported price format is now `date;ticker;close;fx_rate`; additional
  legacy columns are not processed.
- Migration `f6c4a2d8e1b9` batch-rebuilds `prices` on SQLite, preserving rows,
  the foreign key, and `(security_id, date)` uniqueness.
- Added dedicated upgrade/downgrade and data-preservation tests.

### Changed — transactions always use a consistent leaf category

- `category_id` is required and must reference an existing category without
  children; a childless root is a valid leaf.
- Creating the first child of an already used category is blocked while
  that category is referenced; no data is moved automatically.
- Manual entry, CSV preview/import, and internal generators share invariants:
  nonzero amounts, `income > 0`, `expense < 0`, and `transfer` categories
  reserved for the dedicated flow.
- Fully withheld income and sales with costs equal to proceeds remain valid
  without creating zero movements. Adding a cost that would make sale
  proceeds negative is rejected atomically, preserving previous costs and
  the cash movement.
- Legacy negative-net sales are no longer reclassified as Security Costs
  expenses: resynchronization fails explicitly rather than hiding incompatible data.
- Migration `a9e5c7d2b4f1`, after OHLCV removal, makes
  `transactions.category_id` non-nullable and adds `CHECK (amount <> 0)`.
  It checks for incompatible data first and stops without backfill if found.
- New CSV profiles and every import require `category_column`. Legacy
  profiles with `NULL` remain readable, but the wizard requires completing
  the mapping before preview.

### Security — local HTTP boundary and default development database

- Code and `.env.example` now default to `data/pfim-dev.db`: unconfigured
  startup does not implicitly select the operational database name.
- The backend accepts only configured loopback hosts and validates browser
  `Origin` headers.
- Every `POST`, `PUT`, `PATCH`, and `DELETE` requires the volatile capability
  token from `GET /security/capability` in `X-PFIM-Capability`. The frontend
  handles bootstrap and renewal; OpenAPI exposes it through **Authorize**.
- The token stays in memory and changes on restart. It is not multi-user
  authentication: PFIM remains a single-user app not intended for LAN or
  Internet exposure.

### Security — verified online backup and restore foundation

- Replaced direct live-file copying with the SQLite Online Backup API,
  opening the source read-only and producing consistent snapshots even
  during concurrent writes.
- Each backup starts with a unique `.partial` name and is published only
  after integrity, foreign-key and Alembic revision checks, SHA-256 hashing,
  manifest creation, and disk synchronization.
- `BACKUP_ENABLED` and `EXPECTED_ALEMBIC_REVISION` require explicit setup;
  `GET /backup/status` reports effective state, and
  `GET /backup/{filename}/manifest` downloads the verified manifest.
- `make backup`, `scripts/backup.ps1`, API, and UI use the same service;
  documentation treats the database backup and manifest as a pair to retain
  outside the local drive as well.
- Removed the legacy file-copy restore. The new opt-in restore uses only
  verified backups and never progressively copies a file over the live database.

### Fixed — atomic transactions and explicit SQLite concurrency

- Each request uses one transaction: repositories `flush`, commit happens
  at the FastAPI boundary, and any error rolls back the entire composite flow.
- The SQLite driver no longer implicitly decides when to begin a transaction:
  reads use `BEGIN`, mutations use `BEGIN IMMEDIATE`, and every connection
  enables foreign keys and the busy timeout.
- `SQLITE_BUSY` and `SQLITE_LOCKED` become structured PFIM responses without
  false success.
- Concurrent file-backed tests enforce read snapshots, leaf categories,
  aggregate sale costs, double FIFO sales, and import deduplication: the
  second writer rereads committed state or is rejected without partial writes.

### Fixed — net-worth snapshots and temporal lifecycle

- Net-worth reports with `as_of_date` no longer use later trades or prices;
  future snapshots are rejected.
- Without a quote at or before the snapshot, portfolio valuation uses FIFO
  cost and declares the estimate and affected securities in
  `portfolio_valuation` metadata.
- Accounts now have `opened_on` and `closed_on`: new accounts open today
  unless an explicit past date is supplied; legacy `NULL` denotes unknown
  boundaries. Balances and reports respect both temporal limits.
- Dated writes for transactions, transfers, trades, income, recurring costs,
  and linked movements verify the account existed on that date. Reactivation
  cannot erase a historical closure; only a same-day closure can be undone.
- Trades, income, and recurring costs freeze the actual cash account in
  `cash_account_id`. Later investment-account reference changes neither move
  nor resynchronize history onto the new account.
- Migrations `f2b6d8a4c1e9` and `a4c7e9b2d5f8` add local constraints and
  lifecycle dates without inventing legacy references or dates; incompatible
  states fail before modification.
- Migration `b8d1f4a7c2e9` reconstructs `cash_account_id` only from the linked
  cash movement, leaving `NULL` for legacy cases without a recoverable origin.

### Fixed — tax ownership, prices/rates, and inactive securities

- `tax_events.origin` distinguishes `manual`, `automatic_trade`, and
  `legacy_unknown`. Constraints prevent simultaneous sources and multiple
  automatic events per sale. The synchronizer can change or delete only
  rows it owns.
- Prices and rates must be finite, positive, and within application limits
  for their declared scales in both preview and import. SQLite constraints
  from migration `e7b3c9a5d1f4` also protect writes outside the API.
- Price imports correctly report inserts and updates for `(security_id, date)`
  and share parsing and validation with preview.
- Securities with open positions cannot be deactivated. Archived history
  stays readable, but new trades, prices, income, and trade-cost changes are
  blocked in both services and UI write selectors.

### Robustness — bounded, paginated imports and exports

- CSV uploads are read in chunks and rejected above 5 MiB; parsing/import
  stop above 100,000 rows. Size and encoding errors have structured responses.
- Transaction and price previews are paginated (200 rows by default, maximum
  500) while retaining whole-file counts.
- Reports and CSV exports no longer depend on an arbitrary 100,000-transaction
  cap: the repository iterates in batches using keyset pagination.

### Reproducible builds and forecast contract

- Reference runtimes are pinned to Python 3.14.6, Node.js 26.4.0, and npm
  11.17.0 through `.python-version`, `.node-version`, and `engines`.
- `backend/pylock.toml` locks versions, wheels, and hashes for Windows x86-64;
  `scripts/setup.ps1` installs with `--require-hashes`. The frontend uses
  `package-lock.json` through `npm ci`.
- The distinct POSIX path uses versions constrained by
  `constraints-tested-win-py314.txt`, without claiming cross-platform artifact
  guarantees equivalent to the Windows lock.
- Forecast horizon aligned between contract and documentation at 1–50 years.
- React Router explicitly enables the two supported future behaviors in the
  current version 6; E2E smoke testing after reload no longer emits v7
  migration warnings.

### Documentation — normative specification and data safety

- Clarified that `1.0` is the specification version, distinct from application
  release `0.22.0`.
- Introduced `IMPLEMENTED`, `PLANNED`, `SUPERSEDED`, and `OPEN DECISION`
  statuses, with OpenAPI and Alembic as operational sources of truth.
- Aligned stack, architecture, schema, API, frontend, taxation, repository
  structure, and roadmap with the current implementation.
- Incorporated implemented invariants for leaf categories, sign/type
  consistency, nonzero amounts, and transfers through the dedicated flow only.
- Added `docs/data-safety.md`; removed the README procedure recommending
  database deletion on lock errors.
- Added and updated `docs/risk-register.md`, distinguishing open, contained,
  and closed risks, consequences, evidence, and remaining operational issues
  without presenting proposals as verified mitigations.
- Corrected ADRs on SQLite portability and the non-fiscal meaning of FIFO.
- Updated README, setup, and safety guidance with exact runtimes, locked
  installation, HTTP capability, online backup with manifests, and opt-in
  crash-safe restore disabled by default.
## [0.22.0] - 2026-07-29 — Accurate imports and one last-12-month window

### Fixed — CSV imports could report success without saving anything

Two **identical rows in the same file** were not recognized as duplicates:
queries searched only the database, where the first row had not arrived yet.
Both were queued, `import_hash` uniqueness failed at `commit()` after the
response was composed, and the entire import was lost.

```
CSV with two identical rows (two EUR 1.50 coffee purchases on the same day)

HTTP response    200  {"imported": 2, "skipped_duplicates": 0}
rows saved        0
```

Verified against a running Uvicorn server as well as tests. This is an ordinary
case: any statement can contain two identical charges on the same day.

- Deduplication now includes rows encountered **during the current pass**,
  as well as those already in the database.
- The suite hid the defect because `tests/integration/conftest.py` used
  default enabled `autoflush`, while `app.database.SessionLocal` disables it.
  Autoflush makes queries see newly queued rows; without it they do not.
  The fixture now mirrors production parameter by parameter, making the
  defect reproducible.

### Fixed — the same movement silently disappeared from a second account

`import_hash` used date + amount + description and was unique across the table,
so the same salary imported into a second account was discarded as a duplicate.

```
Account A ← "2026-02-10, Salary, 1500"   imported: 1
Account B ← "2026-02-10, Salary, 1500"   skipped_duplicates: 1   balance: 0
```

- The hash now includes `account_id` (`app.utils.deduplication`). Reimporting
  the same file into the **same** account still does not double its balance.
- Amounts are normalized to `Numeric(18, 6)` precision: CSV `-1.5` and
  database `-1.500000` are equivalent. Without a common representation,
  repeat imports would recognize no rows.
- Migration `b7e4d1c9a3f2` **recalculates existing hashes** so previously
  imported statements remain recognizable. Downgrade refuses to proceed if
  removing the account would cause a collision, rather than violating uniqueness.

### Changed — import preview asks for the destination account

`POST /transactions/import/preview` has a new required `account_id` field;
the wizard now selects the account at step 3 rather than step 4.

The preview's Status column identifies duplicates relative to a specific
account. Asking for the account afterward made preview answer a different
question from the operation the user was about to perform.

### Fixed — last 12 months still used two different windows

Version 0.21.0 unified the **constant**, not the **comparison**: one place used
`>= today - 365`, another `> today - 365`, producing 366 versus 365 days.

```
EUR 50 dividend received exactly one year ago

/performance/{id} .yield_on_cost                 5.00  ← included
/reports/dividends-analysis .trailing_12m_net    0     ← excluded
```

- The window now lives in `app.finance.periods.trailing_year_start`, combining
  duration **and** comparison. It contains exactly `DAYS_PER_YEAR` days,
  including today and excluding the day exactly one year ago.
- Aligned the third window, average spending in `net_worth`, which was one
  day longer than the other two.
- Cost-incidence annualization now uses `DAYS_PER_YEAR` instead of a hardcoded
  `Decimal("365")`, the only calendar constant outside the shared module and
  the only previously untested branch of `costs_analysis`.

### Fixed — a coupon could remove money from the account

`tax_withheld > total_amount` was accepted, generating a negative net
**outgoing** cash movement categorized as Coupons and Dividends. Gross income
and withholding must now be nonnegative, and withholding cannot exceed gross
income (422). Fully withheld income with zero net remains valid.

### Added — the first frontend tests

`npm test` previously exited with code 1 because no test files were found.
It now runs 24 Vitest tests for pure `src/lib/` functions: formatters, exchange
rate form rules, and local dates. They enforce two intentional behaviors:
Italian number formatting groups thousands only from five digits
(`1234,50 €`, `12.345,50 €`), and `todayIso()` does not go through UTC.

### Fixed — duplicated negative sign in the Costs tab

The return-drag sign was manually prefixed in text, producing results such as
“−-0.50 p.p.” Drag is usually positive but need not be: sale costs reduce
withdrawn capital and net TWR can exceed gross TWR. The sign now comes from
the data (`formatReturnDrag`).

### Internal

- Frontend version was still `0.1.0` while the backend was `0.21.0`; both
  now follow the CHANGELOG.
- `make lint` and `scripts/lint.ps1` include `backend/migrations`, previously
  the only excluded Python directory, which had drifted into a separate style.
- Added `make test-frontend` and `scripts/test-frontend.ps1`; `make test`
  runs both suites.
- Backend: 370 tests, up from 341. Frontend: 24, up from 0.

## [0.21.0] - 2026-07-29 — One value per indicator; tax register follows FIFO

### Fixed — Yield on Cost was 5% in one report and 500% in another

`/performance/{id}` divided **total income** by **average cost per unit**:
a total divided by a unit value, multiplying the correct percentage by
units held.

```
100 shares at EUR 10 (EUR 1,000 invested), EUR 50 net dividends

/performance/{id}.yield_on_cost                        500   ← incorrect
/reports/dividends-analysis .yield_on_cost_pct           5.00 ← correct
```

- **One implementation** in `app.finance.income`, called by both endpoints,
  divides totals by totals. Fixed the same defect in `current_yield`, which
  divided by unit price instead of total position value.
- Neither metric appeared on a screen; the inconsistency was in the API
  published through `/docs`.
- `tests/integration/test_yield_consistency.py` enforces that **yield does not
  depend on how an investment is divided into units**.

### Fixed — the tax register did not follow FIFO recalculation

A sale's realized gain depends on the lots open at that time, but its amount
was calculated only at creation and never updated.

```
buy 5@100 · buy 5@200 · sell 5@300 · sell 3@400
DELETE the first sale

/portfolio/summary .total_realized_gain_loss     900   ← recalculated FIFO
/reports/costs-analysis .fiscal.capital_gains    600   ← stale value
```

EUR 300 of taxable income disappeared from the tax report while remaining
visible on the Portfolio page.

- `TaxService.sync_capital_gain_events` aligns automatic events after **every**
  write affecting a security's trades, including purchases: backdated
  purchases also change later sales' taxable amounts and had the same defect.
- Events are **updated instead of recreated**: IDs, notes, and manually set
  `is_compensated` flags survive (§11.1, editable register). Automatic
  descriptions are rewritten only if they have not been customized.
- Break-even sales lose their tax entry; manual entries remain untouched.
- Added FIFO `realized_by_sell_eur`: the capital gain/loss for **each** sale,
  alongside the total.

### Fixed — `sqlite:///:memory:` was not an in-memory database

In `.env`, it was treated as a relative path and attempted to open a file
called `:memory:` in `backend/`, an illegal Windows filename. In-memory
values and `file:...?uri=true` URIs now pass through unchanged.
`tests/unit/test_database_url.py` covers this previously untested startup
function, where a failure prevents application launch instead of merely
failing a test.

### Fixed — undefined type in the CSV profile service

`CsvImportProfileCreate` was annotated but never imported. Unevaluated
annotations avoided runtime failure, but tools inspecting them found an
undefined name. This was also the only API resource without tests; it now
has seven.

### Changed — average spending no longer treats refunds as expenses

Amounts were summed as absolute values per row: a refund or credit note in
an expense category **increased** average spending and lowered runway.
Amounts are now summed with their signs.

### Changed — last 12 months has one meaning everywhere

Security yield used 360 days (12 × 30), while coupon analysis used 365;
boundary income appeared in one count but not the other. Calendar conventions
now live in `app.finance.periods`.

### Removed — two ineffective checkboxes

Include dividends and Reinvest dividends in Forecasts were never read by
the projection engine and did not change results. Expected return is total
return, including dividends; a note now states this. Separate handling would
require a separately declared dividend yield.

### Performance — `/performance/portfolio` no longer scales with security count

Trades were preloaded, then `security_performance` reread income, prices,
and trades from scratch for each security.

```
 2 securities    24 queries -> 16
10 securities    64 queries -> 16
```

`tests/integration/test_performance_query_budget.py` fails if query cost
again grows with the catalog. Removed a per-row category-name query from
category analysis where an in-memory map was already available.

### Internal — fewer duplicate implementations

- **`BaseRepository`** centralizes identical ID lookup, insertion, updating,
  and deletion across ten repositories: about 190 fewer lines and one place
  to fix shared behavior.
- **`LinkedCashMovement`** replaces three copies of trade, coupon, and cost
  cash synchronization. Three `TransactionRepository.get_by_*_id` methods
  become `get_by_link`.
- **`fx_rate_description`** centralizes four schema copies with three
  different phrasings of the same exchange-rate rule.
- **`todayIso()`** replaces eight uses of `toISOString()`, which returns the
  **UTC** date and suggested yesterday between local midnight and 2 a.m.
- **`withholding_eur`** derives EUR withholding from gross minus net instead
  of reconverting the table's only native-currency column.
- Removed the unreachable `transfer_group_id` branch from
  `_raise_if_generated_elsewhere`, which misleadingly looked like an active guard.
- Moved `PriceRepository.get_as_of` into its only consuming test.

### Tests — 272 to 333, coverage from 94% to 97%

- **Migrations versus models:** `alembic upgrade head` on an empty database,
  compared against `Base.metadata` table by table and column by column.
  Other tests use `create_all` for speed and did not verify the production path.
- **CSV report exports:** nine previously uncovered `format=csv` branches;
  `reports.py` rose from 71% to 100% coverage.
- **CSV import preview:** the step users see before any write must write nothing.
- **Backup downloads:** including both path-traversal defenses.
- **`DATABASE_URL` resolution:** relative, absolute, in-memory, and URI values.
- Resolved all Ruff warnings; added `backend/pyproject.toml`, without which
  `make lint` would reformat 117 of 129 files into an unchosen style.
- `path_separator = os` in `alembic.ini` replaces `version_path_separator`,
  deprecated in Alembic 1.16. The historical space/comma/colon splitting could
  incorrectly split Windows drive letters.

### Documentation

- `/reports/net-worth` and `/reports/income-statement` now declare
  `response_model`; they were the only reports lacking schemas on `/docs`.
- `docs/finance-calculations.md`: §2.1 explains that simple and total return
  measure only open positions and ignore realized results; §3 fixes YoC and
  Current Yield dimensional consistency; §7.1 adds tax-register synchronization.
- `docs/multi-currency.md`: explains that `income_events.tax_withheld` is the
  only native field without a dedicated EUR column and how to derive it.
- README: Vite 7 instead of 5, eight missing endpoints, `app.finance.periods`,
  and `pyproject.toml`.
- Removed the `/api` proxy from `vite.config.ts`: the client uses absolute
  addresses, so it was unused and made backend CORS look unnecessary.

## [0.20.0] - 2026-07-28 — Capital losses offset capital gains

### Fixed — two reports calculated different taxes from identical data

For EUR 1,000 capital gain, EUR 600 capital loss, and a 26% rate:

```
/reports/tax-register    EUR 104.00 = 26% of offset net amount (400)
/reports/costs-analysis  EUR 260.00 = 26% of the gain alone (1,000)
```

The same concept was calculated in **three places**. `TaxService` stored tax
on each isolated gain, `costs-analysis` summed those values, and `tax-register`
recalculated from the net. The list's Tax column showed the first value while
its export reported the second.

- **`fiscal_position`** is now the single tax calculation and applies loss
  offsetting: the rate applies to the net, never each isolated gain. The
  correct value is 104.
- The **Net result (gross − costs)** KPI is consequently no longer understated.

### Changed — withholding is deducted rather than ignored

- Actual tax withheld on a sale is **subtracted** from the estimate instead
  of removing the entire estimate. For a gain of 500 with 118 withheld, a
  residual estimate of 12 remains; previously the difference between broker
  withholding and the recorded basis was hidden.
- **Stamp duty** recorded on a trade no longer reduces capital-gains tax:
  it taxes assets instead.

### Removed — the Tax Register report

- Removed `GET /reports/tax-register` and its tab: five of six aggregates
  duplicated Costs and Tax, and one disagreed.
- Free-form tax entry (§11.1) **remains** inside Costs and Tax for information
  the system cannot infer, such as previous losses or external withholding.
  Without it, offsetting would use only automatically generated data.
- One tax tab now shows the **complete calculation**: gains → offsetting →
  taxable base → rate → withheld → due, explaining the resulting total.

### Changed

- Per-event `tax_amount` remains stored as **detail**, representing gross
  tax before offsetting, documented in the model, schema, and API. It no
  longer contributes to totals.

### Tests

- Increased from 258 to **272**. `test_fiscal_position.py` covers offsetting,
  loss periods, cross-year limits, withholding, stamp-duty exclusion, and
  consistency between cost entries and the tax section.

### Documentation

- Rewrote specification §11.4 with the complete formula, the definition of
  already-withheld tax, and v1.0's two limits: no multiyear loss carryforward
  and no distinction between miscellaneous income and capital income, which
  determines eligible offsetting instruments in Italy.
- `docs/finance-calculations.md` §7 covers the single calculation and §8 its limits.

## [0.19.0] - 2026-07-28 — Performance, one expense definition, reduced API surface

### Fixed — net-worth history took more than a minute

- The default Net Worth report valued the portfolio **date by date**:
  five years of movements required **45,764 queries and 76 seconds**.
- Data is now loaded once and scanned with a cursor, updating FIFO trade
  by trade rather than rebuilding it: **5 queries and 250 ms**.
- Similar improvements in other reports: Costs and Tax from 8.8 s to 0.26 s,
  trades from 181 queries to 2, and portfolio from 41 to 3.

| Endpoint | Before | After |
|---|---|---|
| `/reports/net-worth/history` | 75,918 ms / 45,764 queries | **252 ms / 5** |
| `/reports/costs-analysis` | 8,838 ms / 5,446 | **255 ms / 28** |
| `/performance/portfolio` | 5,237 ms / 2,635 | **1,785 ms / 114** |
| `/reports/securities-analysis` | 142 ms / 61 | **28 ms / 4** |
| `/trades` | 196 ms / 181 | **22 ms / 2** |

- Added indexes required by §12.3 but never created: transaction date,
  account, and category; trade security and account.
- FIFO now has an incremental `PositionTracker` wrapped by
  `calculate_position`: one implementation used in two ways.

### Changed — one definition of income and expenses

Three definitions coexisted: the income statement filtered nothing, category
analysis filtered by type, and average spending additionally excluded transfers
and security purchases. The app gave inconsistent answers to how much was spent.

- **Income statement, expense analysis, income analysis, and average spending**
  now share the rule: exclude both sides of owned-account transfers and
  security-trade cash movements; include coupons and recurring costs.
  Specification §7.5's rule is applied consistently.
- Gross income and expenses fall, the savings rate becomes realistic, and
  the Dashboard chart no longer shows an expense spike when an ETF is bought.
  The net amount is unchanged.
- **Account balances** remain cash views and count everything to match statements.

### Fixed — Transfer Analysis always showed EUR 0.00

- Both sides canceled, making the total zero regardless of the amount moved.
- The report now counts only the outgoing side and reports **transferred volume**.

### Added — specified features without an interface

- **Reports → Tax Register** (§11.1): free-form tax entries, with automatic
  gains/losses labeled and protected from direct editing.
- **CSV export on each report** (§8.4): added the missing frontend button
  for the existing backend export, using the displayed period.
- **Scenario comparison** in Forecasts (§6.9): overlays base curves from
  multiple saved scenarios.

### Changed — one transaction per request

- Repositories use `flush` instead of `commit`; commit happens once on request exit.
- Recording a sale writes the trade, tax event, cash movement, and historical
  price. Previously separate commits could leave a sale without its cash
  movement after an intermediate error; now all writes succeed or none do.
- Enabled SQLite **foreign keys** with `PRAGMA foreign_keys=ON`. Deleting a
  security previously left its prices behind; children are now deleted
  explicitly with their parent.
- **Validation errors** follow §3.3's schema. FastAPI's previous format lacked
  `message`, causing the UI to display API error 422 rather than the reason.

### Removed

- **PUT updates on transactions, trades, categories, income events, recurring
  costs, CSV profiles, and scenarios**: correct by deleting and recreating.
  Updates remain for `accounts`, `tax-settings`, `tax-events`, and
  `securities`, each with its reason documented in §6.
- `GET /income-events/calendar`, identical to `GET /income-events`, and
  `GET /reports/portfolio-performance`, an alias of `/performance/portfolio`.
- Unused repository abstractions, utilities, error types, sample state store,
  and empty directories; unused `CsvProfile` fields `encoding` and
  `amount_sign_convention`.
- Consolidated two price upsert implementations; `ImportService` had omitted
  conversion fields.
- **11 declared but never imported dependencies**: `pandas`, `numpy-financial`,
  `python-dateutil`, `@tanstack/react-table`, `date-fns`, `react-hook-form`,
  `zod`, `@hookform/resolvers`, `clsx`, `lucide-react`, and `zustand`.

### Tests

- Increased from 231 to **258**, coverage from 92% to **94%**.
- `test_portfolio_value_series.py` retains naive valuation as a **reference**,
  checks exact equivalence, and prevents query cost scaling with date count.
- `test_economic_movements.py` enforces one expense definition across reports.
- `test_transaction_boundary.py` verifies that composite-operation failures
  leave nothing partially written.
- `test_api_surface.py` documents removed endpoints and the four update
  exceptions, preventing accidental reintroduction.

### Documentation

- Specification §5.4 defines income/expenses, §6 describes update rules and
  exceptions, and §11.4 covers the new tab; API contracts match actual endpoints.
- README Port already in use guidance replaces unavailable Windows
  `lsof`/`kill` commands with PowerShell equivalents and explains
  `WinError 10013`, which often indicates an occupied port despite its
  permissions wording.
- `docs/finance-calculations.md` covers incremental FIFO and aggregate-read costs.
- README endpoints, directory structure, and stack aligned.
## [0.18.0] - 2026-07-28 — Multiple currencies: conversion at entry

Multiple currencies existed in the schema but had never been fully applied:
exchange rates were looked up at runtime in six places, each handling missing
rates differently. This release addresses the resulting inconsistencies.

**One rule:** every incoming amount declares its currency and, for non-euro
amounts, the exchange rate at that time. Its EUR value is calculated and frozen
when saved. All subsequent totals sum euros. See `docs/multi-currency.md`.

### Fixed — identical data produced different totals

- **`securities-analysis` reported a different invested amount from
  `portfolio/summary`** for the same portfolio, reconverting cost basis at
  TODAY'S rate instead of the historical rate: EUR 1,800 versus EUR 1,780
  in a test portfolio.
- **The tax register summed withholding in native currency** while cost
  analysis converted it: 7.50 in one report and EUR 6.83 in another.
- **Account balances, net worth, income statements, and category analysis
  summed `amount`** instead of `amount_eur`: a USD 100 expense was subtracted
  as EUR 100.
- **Net worth summed accounts in different currencies** without conversion.

### Fixed — operations missing from cash balances

- Foreign-currency operations **without an available exchange rate were
  recorded without any cash movement**, silently leaving account balances stale.
- The position counted fully toward **invested capital but had zero market
  value**, inventing a loss equal to the entire investment.
- Exchange rates are now required at entry, preventing this state.

### Fixed — the interface displayed euro symbols on dollar values

- Foreign securities' average price, current price, and trade prices were
  formatted as euros despite being native-currency values.
- Detail rows now show native values beside EUR equivalents
  (`$ 210.00 (EUR 193.20)`); totals remain in euros only.
- Positions expose two percentages: **EUR** return reflects the investor's
  actual return; **native** return isolates price movements.

### Added

- **Currency and exchange-rate fields** in every form: movements, transfers,
  trades, trade costs, recurring costs, income, prices, and CSV imports.
  The rate field appears **only** when needed and suggests the latest
  archived rate on or before the date.
- **Settings → Exchange-rate archive:** the backend import previously had
  no screen, so multiple currencies could not be configured through the app.
- `GET /fx-rates/suggest` suggests a plausible rate for a date.
- Optional `fx_rate` in price CSV, required only for non-EUR securities;
  **existing files continue working unchanged**.
- Trades can now be entered in foreign currency through the UI; the form
  previously kept currency state without an input control.

### Changed

- **Accounts are EUR-only**, with an explicit message. Balances sum already
  converted movements; foreign-currency accounts would mix units between
  opening and current balances. Foreign movements belong to EUR accounts
  and declare their own currency and rate.
- **Percentage costs inherit the trade's currency and rate**, as a fraction
  of its converted value. The previous schema described a conversion the
  code did not perform.
- `*_eur` and `fx_rate` columns are **NOT NULL** in every table; missing
  columns were added to `prices`, `trade_costs`, and `portfolio_costs`.
- Replaced six `_find_fx_rate` implementations with pure
  `app/finance/currency.py` and an adapter producing readable 400 errors.
- Standardized cache invalidation so Dashboard and Report KPIs update
  immediately after movements and trades.
- Cash Flow previously offered a silently failing Delete action on
  **recurring-cost** transactions. These now show that they are managed
  elsewhere, and deletion errors are displayed.

### Migration

`d9f2a4c7e3b1` reconstructs missing EUR values in reliability order: EUR rate 1,
rate derived from converted/native values, then for prices the latest archived
rate not after the date. It **prints a warning** naming securities that required
a fallback of 1 for manual review. Validated on empty databases and through
round-trip downgrade/upgrade.

### Tests

- 49 new tests: missing-rate rejection for every entity, EUR fixed at 1,
  correct conversion, **cross-report consistency**, foreign-position
  zero-valuation regression, and rate archives as suggestions only.
- Suite increased from 182 to 231 tests, coverage from 91% to 92%; both
  conversion modules reached 100%.

### Documentation

- Added `docs/multi-currency.md`: the rule, rationale, and special cases.
- Rewrote `docs/finance-calculations.md`, previously only TODOs, to explain
  FIFO, TWR, MWR/XIRR, annualization, projections, and v1.0 limits.
- Fixed README's Finance Engine import example, coverage figure, outdated
  Poetry reference, completed roadmap, and database reconstruction command
  that bypassed Alembic.
- `docs/csv-formats.md`: corrected price/rate delimiter from comma to semicolon.
- `docs/setup.md`: removed the claim that no real migrations existed.
- Rewrote specification §9.8 around the implemented rule.

## [0.17.1] - 2026-07-27 — TWR starts at the first trade

### Fixed — incorrectly dated income erased TWR

- Measurement started at the first **flow**, including coupons and dividends.
  Income before the first purchase, whether a typo or a distribution on a
  closed and repurchased position, opened the period on an **empty** portfolio
  with zero starting capital, making TWR unavailable for the whole history.
- The period now starts at the **first trade**, when the portfolio begins to
  exist. Earlier flows are discarded because they cannot have affected it.
- Applied the same correction to `investment_period_days` for annualization.
- **Test:** income 20 days before the first purchase must not prevent TWR;
  the period must begin at purchase.

## [0.17.0] - 2026-07-27 — Visible formulas for every indicator

### Added — how each number is calculated

- Every KPI displays its **calculation formula** on hover or keyboard focus,
  highlighting the formula and explaining inclusions, exclusions, and when
  the value is unavailable.
- Covers Dashboard, Portfolio, and Report KPIs: net worth, cash and runway,
  cumulative and annualized TWR/MWR, concentration, income, costs and
  performance impact, and income statements.
- **Account balance and available cash can differ unexpectedly:** the former
  includes investment accounts and the latter excludes them, so a negative
  investment-account balance can make available cash larger than total
  account balances. Formula explanations clarify this behavior.

### Changed — shared KpiCard

- Replaced three identical implementations in Dashboard, Portfolio, and
  Reports with `components/common/KpiCard.tsx`, also centralizing formula support.

## [0.16.0] - 2026-07-26 — Risk and liquidity indicators

Filled four indicator gaps using existing data without requiring new user entries.

### Fixed — net-worth history showed cash only

- The chart summed account balances, so it **fell when securities were bought**,
  although money had become securities and net worth had not fallen.
- It now stacks **cash** and **portfolio value** at each date, with a total
  **net-worth** line. `net-worth/history` exposes all three separately.

### Added — available cash and runway

- Available cash excluding investment accounts, average monthly spending over
  the last 12 months, and **runway months** = cash / average spending, with
  a warning below three months. Both underlying values already existed.
- Average spending **excludes security purchases and owned-account transfers**,
  preventing artificially low runway in investment months.

### Added — portfolio concentration

- Largest, top-three, and top-five security weights, plus **effective securities**
  (`1/Σw²`, inverse Herfindahl index): the equivalent number of equally weighted
  holdings. Ten securities with one at 80% still produce a value near one.
- Value rankings identified the largest holdings but did not quantify how
  dependent the portfolio was on them.

### Added — currency exposure

- Portfolio breakdown by currency, highlighting the share exposed to exchange
  rates. The EUR-normalized application previously provided no overview of
  foreign-currency exposure.

### Tests

- Nine new tests for concentration (uneven, equally weighted, and empty
  portfolios), converted currency exposure, runway calculation and exclusions,
  no-expense states, investment-account exclusion, and net-worth history
  including portfolio value. **181 total tests**.

### Fixed — inconsistent 12-month window

- `_average_monthly_expenses` subtracted 30-day months but divided by 30.44,
  making the window effectively 11.8 months and distorting the average.
  It now uses a full year.

## [0.15.0] - 2026-07-26 — Income analysis and automatic trade prices

### Added — automatically save a price for every trade

- Recording a purchase or sale adds its price to history (`source='trade'`):
  a trade is an observed market price for that date.
- Resolves the inconsistency that made TWR unavailable in v0.14.0: portfolio
  valuation on a date can no longer fall below that day's sale proceeds.
- **Never overwrites an existing price** for the date. Manual/imported closing
  prices remain authoritative; execution prices only fill gaps.
- Applies identically to buys and sells because both can expose the same
  valuation inconsistency.

### Added — Income Analysis tab

New Report tab (`GET /reports/dividends-analysis`) complements the income-entry
page (§7.5.1):

- **Indicators:** net income, withholding and percentage, trailing 12-month
  income, portfolio **yield on cost**, payment count, first/last payment,
  and monthly average.
- **Yearly accumulation:** net/withholding bars with cumulative line and
  a table of year-over-year change.
- **Distribution within the year:** income grouped by month across all years,
  showing regularity or seasonality.
- **Instrument-type** and **event-type** breakdowns: dividends, coupons,
  and capital repayments.
- **Securities ranked by income**, including total share and individual
  yield on cost, calculated only for positions still open.

**Yield on cost** compares receipts with cost basis instead of market value,
measuring income return on the capital actually invested.

### Fixed — empty pie charts with negative net amounts

- Withholding above gross income produced negative net values that a pie chart
  could not represent. Charts now include positive values only and show
  No positive net income in the period when none remain.

### Changed — shared period selector

- Replaced slightly different From/To filters across analysis tabs with
  `DateRangeFilter`, including shortcuts for the last three calendar years.

### Tests

- Nine new tests: trade-recorded price, existing-price preservation, coherent
  valuation after sale with calculable TWR, and six income-analysis cases
  covering yearly growth, rankings and yield, breakdowns, 12-month seasonality,
  period filters, and empty states. **172 total tests**.

## [0.14.0] - 2026-07-26 — Costs and Tax, recurring costs, Dashboard context

### Changed — Tax report becomes Costs and Tax

The tab measures **investment costs and their effect on performance**
(specification §11.6) in three sections:

- **Gross realized result:** gains, losses, and gross coupons. Losses remain
  here rather than among costs because they are market losses, not fees paid
  regardless of performance.
- **Incurred costs:** tax, operating, and recurring groups, with a pie chart,
  itemized detail, and gross-to-net reconciliation.
- **Performance impact:** percentages of invested capital and gross result,
  annual incidence comparable to ETF TER, and return drag in percentage points.

Each item is labeled **actual** or **estimated**. At this release, actual sale
withholding suppressed that sale's rate-based estimate; estimated stamp duty
appeared only until actual duty was recorded in the period, avoiding double counts.

At this release, `GET /reports/tax-register` remained available through the API
for CSV exports, but no longer had its own UI tab.

### Added — recurring portfolio costs

- New `portfolio_costs` table (§11.5) for stamp duty, custody, and fees charged
  to the whole portfolio rather than one trade. Enter through
  **Securities → Recurring costs**.
- Each cost generates a linked cash outflow in the **reference account**
  (§5.2), categorized as Security Costs and not editable from Cash Flow.
  This prevents overstated net worth.
- The previously unused **stamp-duty rate** in Settings now feeds the
  report's annual estimate.
- Added `GET/POST/PUT/DELETE /portfolio-costs` endpoints.

### Added — TWR net of costs

- `portfolio_twr(net_of_costs=True)` includes commissions and recurring costs
  in flows: buys require extra capital for the same units, sales withdraw less,
  and recurring costs contribute capital without producing units.
- Opening-day costs are added to initial capital because that day is not
  processed as a flow; otherwise the **first** purchase's fee would never
  affect return.
- Net Worth still displays gross TWR, now labeled explicitly.

### Fixed — extreme TWR from inconsistent data

- `time_weighted_return` rejected zero opening capital but not **negative**
  capital. A withdrawal exceeding portfolio valuation, often because the
  stored price was older or different from execution, produced negative
  subperiod capital and economically meaningless ratios such as **−347%**.
- This now raises an error: TWR is `null` and the UI shows an em dash rather
  than an invented number. The preexisting issue surfaced while comparing
  gross and net performance.

### Added — Dashboard context panel

- An introductory panel explains the application and how Cash Flow,
  Securities/Portfolio, and Reports/Forecasts connect, helping new and
  returning users orient themselves.

### Tests

- Eleven new integration tests cover reference-account cash routing,
  Cash Flow edit protection, actual-versus-estimated taxes, stamp duty,
  net/gross TWR, impact metrics, and period filters; a unit test covers
  negative opening capital. **163 total tests**.

## [0.13.0] - 2026-07-26 — Annualized returns, instrument types, security analysis

### Added — annualized returns

- Finance Engine `annualize()` (CAGR, specification §9.5.1) converts cumulative
  return to compound annual return for comparisons across different durations.
- Portfolio Growth now separates **Annualized** (annual TWR, MWR/IRR, and
  Total Return) from **Cumulative over the whole period**, with explicit
  years and days since the first trade.
- **MWR is not annualized twice:** XIRR already discounts annual cash flows,
  so its value remains annual and appears only in the annualized group.
- Added API fields `total_return_annualized`,
  `time_weighted_return_annualized`, and `investment_period_days`.
- **Tests:** five annualization unit tests and two integration cases:
  one-year annualized return ≈ cumulative return, and +100% over four years
  ≈ +18.92% annually.

### Added — new instrument types

- Types now include Stock, Bond, **Equity ETF**, **Bond ETF**, Fund, and
  **Commodities**. Separating equity and bond ETFs makes asset allocation
  distinguish their underlying exposure instead of hiding both under ETF.
- Legacy `etf` remains readable for existing records but is no longer offered
  during creation.

### Fixed — entered and displayed types differed

- The security catalog and Dashboard allocation chart displayed raw database
  identifiers such as `stock` and `bond` instead of the form's labels.
- `frontend/src/lib/securityTypes.ts` now defines labels once for tables,
  charts, and dropdowns.

### Fixed — invisible pie charts

- With `React.StrictMode` double mounting, Recharts 2.x entrance animation
  could be interrupted, leaving all sectors at zero degrees. Pie charts now
  use `isAnimationActive={false}`. Bars were unaffected, which had hidden
  the problem.

### Added — Security Analysis report

- New **Security Analysis** Report tab (`GET /reports/securities-analysis`)
  snapshots the **current** portfolio rather than trade movements;
  fully sold securities are excluded.
- Includes value/open-position/instrument-type KPIs, allocation pie chart
  with value/percentage/security counts, and **Top 10 by value, gains, and losses**.
- Amounts and allocation use EUR (§9.8); at this release, gain/loss percentages
  used native currency, independent of exchange rates.
- **Tests:** four integration tests, including fully liquidated-position exclusion.

## [0.12.0] - 2026-07-26 — Portfolio TWR/MWR, consistent analysis, CSV delimiter
### Fixed — price and exchange-rate CSV delimiters

- **Format change:** price and rate imports now use `;` instead of `,`.
  Comma-separated files split decimal-comma prices such as `17,50` into
  two columns and misaligned the row.
- Decimal commas and decimal points (`17,50` or `17.50`) are both accepted
  and normalized.
- **Files using the old CSV format must be resaved with `;`.**

### Changed — consistent expense, income, and transfer analysis

- All three Report tabs now share **one response schema and one UI component**,
  displaying identical statistics for direct comparison. Expense Analysis
  previously had charts and top movements while the others had text lists only.
- Each tab provides a **date-range selector**, **category pie chart**,
  **monthly bar chart**, **Top 10 categories**, and **Top 10 movements**.
- Categories sort by descending **absolute value**, placing the most relevant
  item first regardless of sign.
- **API breaking change:** `/reports/spending-analysis` now returns
  `total_amount` and `by_category[].total_amount` instead of `total_expense`;
  all three endpoints gain `by_month`.

### Added — portfolio growth metrics (TWR/MWR)

- New **Portfolio Growth** section in Net Worth with **TWR**, **MWR/IRR**,
  Total Return, received income, and per-security detail. Finance Engine
  metrics previously lacked aggregate calculations and UI exposure.
- `PortfolioPerformance` adds `time_weighted_return` and
  `money_weighted_return`, both nullable when unavailable.
- TWR values historical positions using the then-new
  `PriceRepository.get_as_of`; absent historical prices fall back to FIFO
  cost, supporting sparse manually entered price histories.
- Coupons and dividends are outgoing portfolio flows because cash goes to
  the reference account (§5.2). Excluding them would measure only price
  appreciation and ignore income.
- **Tests:** three new cases, including TWR neutrality to contribution timing:
  purchases at different prices must not distort pure price returns.

### Changed — clearer CSV templates in Settings

- Renamed the section CSV import templates — Cash Flow transactions,
  explicitly distinguishing these configurable profiles from fixed-format
  security-price imports.

## [0.11.1] - 2026-07-26 — Price CSV preview and consistent income forms

### Added — price CSV import preview

- New **Import CSV** wizard in Securities → Prices: upload, row-by-row
  preview, and confirmation, following transaction-import UX without column
  mapping because prices use a fixed format. At this release that format
  was `date,ticker,close,open,high,low,volume`.
- New `POST /prices/import/preview` dry run reports new prices, updates,
  unrecognized tickers, and format errors without database writes. Existing
  `POST /prices/import` remains the confirmation endpoint.
- **Tests:** two integration cases for new/update rows, unknown tickers,
  malformed rows, and preview write isolation.

### Fixed — consistent income-form dimensions

- Every field now shares a label-above-input layout and consistent dimensions.
  Previously dates had labels while selects and amounts did not, creating
  uneven heights within the same row.

## [0.11.0] - 2026-07-25 — Investment/reference accounts, prices, reports, and usability

### Added — separation of investment and cash accounts

- **`accounts.reference_account_id`:** every investment account requires a
  checking/savings/cash reference account, never another investment account,
  configured in Settings. **Behavior change from v0.10.0:** trade and income
  cash transactions now always use that reference; investment accounts never
  hold their own cash.
- Trades and income can be recorded **only** on investment accounts (400
  otherwise). Investment accounts are excluded from manual Cash Flow entries
  and transfers.
- **Tests:** seven cases cover required/valid references, referenced-account
  deletion blocking, and manual transaction/transfer rejection on investments.

### Added — security prices

- Added the missing **Prices** UI in Securities, showing latest price/date
  and a quick-entry form. Previously only a CSV backend import existed.
  New `POST /prices` supports single-price entry.
- **Price dates are always explicit** in Securities and Portfolio, with an
  age warning after seven days. Valuation still uses the latest available
  price, even when old, while clearly showing freshness.

### Added — percentage trade costs and visible cost totals

- Trade costs accept fixed amounts **or percentages** of the trade total,
  with calculation preview and EUR amount frozen at save time.
- Added informational `trade_costs.percentage_used`.
- Securities' trade table now shows total Costs without requiring the modal.

### Added — simplified income entry

- `amount_per_unit` and `quantity_held` are no longer required; only gross
  total and withholding are needed. Both fields remain optional in the model.

### Added — security deletion

- Added `DELETE /securities/{id}`, blocked with 409 for linked trades/income,
  and a confirmed Delete action in Securities.

### Added — extended reports

- **Income Analysis** and **Transfer Analysis** gain category breakdowns and
  top movements, previously available only for expenses.
- **Aggregate net-worth history:** a Report → Net Worth chart combines
  balances from all active accounts instead of displaying only one account.

### Added — Cash Flow sorting and period filter

- Clickable Date/Account/Category/Amount headers cycle through ascending,
  descending, and default order; added From/To period filtering.

### Added — explicit forecast parameters

- Starting net worth (automatic or explicit), annual income/expense growth,
  and dividend inclusion/reinvestment became editable instead of hardcoded.

### Tests

- **132 backend tests, all passing**, up 17 from v0.10.0.

## [0.10.0] - 2026-07-24 — Trades and income move cash between connected accounts

### Added

- **Security trades generate linked cash transactions:** purchases create
  outflows of price × quantity + costs; sales create inflows of price ×
  quantity − costs. Previously account balances and portfolio values were
  disconnected, double-counting net worth because spent cash remained in
  the account while acquired securities also counted in the portfolio.
- **Coupons and dividends generate linked net cash transactions**, after
  withholding, credited to the account.
- **Trade-cost UI:** Securities gains a Costs modal for adding/removing
  commissions, taxes, and spreads. Every change recalculates the linked
  transaction. Added `DELETE /trades/{id}/costs/{cost_id}`.
- **Dedicated automatic categories** — Security Purchase, Security Sale,
  and Coupons and Dividends — are recreated on demand if removed, keeping
  security movements visible in analysis and income statements.
- **Generated transactions cannot be edited/deleted directly from Cash Flow**
  (409, managed by Securities/Income). Changes must come through their source
  trade or income event, which updates/removes the linked transaction.
- **Subcategory-type validation:** children must share their parent's
  income/expense/transfer type (400 otherwise); categories with children
  cannot change type (409).
- **Settings groups categories by type** in three color-bordered sections:
  Income, Expenses, and Transfers. Parent selection offers only compatible
  categories.
- **Tests:** 14 new backend tests for linked cash, cost recalculation,
  cascading deletion, direct edit/delete protection, and subcategory types;
  **115 total tests, all passing**.

### Fixed

- Updated `test_net_worth_report_combines_accounts_and_portfolio` to verify
  correct net worth without double counting: EUR 5,000 cash, a EUR 1,400
  purchase now worth EUR 1,700 → EUR 5,300 net worth, not EUR 6,700.

## [0.9.0] - 2026-07-24 — Subcategories, layout fixes, and account transfers

### Added

- **Subcategories in Settings:** category creation gains a parent selector
  limited to top-level categories, matching the backend's two-level limit.
  Selecting a parent inherits its type; children appear indented underneath.
- **Account transfers:** dedicated Cash Flow action accepts source,
  destination, date, and amount. It creates two transactions linked by
  `transfer_group_id`, negative at source and positive at destination, both
  categorized Account Transfer. Individual editing is blocked (409);
  deleting either deletes both. Added `POST /transactions/transfer`.
  Previously transfer was only a category type on an unlinked transaction.
- **Tests:** four transfer tests cover paired creation, same-account rejection,
  cascading deletion, and edit protection; **104 total tests, all passing**.

### Fixed

- Long category names no longer overlap in Settings. Full-width rows replace
  the narrow grid, with truncated text, full-name tooltips, and separate
  delete controls.

## [0.8.2] - 2026-07-24 — Fully quoted CSV rows

### Fixed

- Some exports, especially Excel using local `;` separators, quote each
  entire row instead of individual fields, for example
  `"Date;Description;Amount;Category"`. Standard CSV parsing treated this
  as one header field, failing every preview/import row regardless of profile.
  `parse_csv_content` now detects nonempty rows all starting/ending in quotes
  and containing the delimiter, then removes the outer quote pair before
  parsing. Valid individually quoted fields remain unchanged.
- **Tests:** three parser tests reproduce the pattern, preserve normal CSV,
  and protect legitimate quoted fields; **100 total tests, all passing**.

## [0.8.1] - 2026-07-23 — Delete accounts and categories from Settings

### Added

- **Account deletion:** new `DELETE /accounts/{id}` permanently deletes,
  blocked with 409 for linked transactions/trades. Soft deletion moves to
  `POST /accounts/{id}/deactivate`. Both UI actions are available, with
  confirmation for permanent deletion.
- **System-category deletion:** removed `is_system` protection from
  `DELETE /categories/{id}`. Any category can be deleted if unused and
  childless (409 otherwise). System-category Delete controls now include
  confirmation as well.
- **Tests:** four cases cover used account/category deletion blocking and
  deletable system categories; **97 total tests, all passing**.

### Internal breaking change

`DELETE /accounts/{id}` permanently deletes instead of deactivating.
Soft-delete callers must use `POST /accounts/{id}/deactivate`.

## [0.8.0] - 2026-07-23 — Securities/Income pages, deletion confirmation, CSV profiles

### Added

- **Deletion confirmation** through `useConfirmDialog` for Cash Flow
  transactions, security trades, and income events.
- **Securities page** (`/securities`) provides a catalog and register of
  **all** purchases/sales, with creation and confirmed deletion. Portfolio
  remains a read-only snapshot of current quantities and market values.
- **Income page** (`/income-events`) provides dividend/coupon/capital-repayment
  entry and an event table with total net receipts and confirmed deletion.
- **Transaction CSV categories:** profile mappings gained a category column.
  Values resolve case-insensitively against existing categories; unknown
  categories block their row in preview/import without automatic creation.
- **Persistent CSV templates** in `csv_import_profiles`, exposed through
  `/csv-import-profiles`, replace hardcoded bank profiles and are configured
  in Settings. Fresh installations start without preset profiles.
- **One-click Windows launcher** (`start.bat`) starts backend/frontend in
  separate windows and opens `http://localhost:5173`, checking that venv and
  node_modules have been installed first.
- **Tests:** 93 backend tests passing without regressions.

### Changed

- Exposed `GET /trades` and `useDeleteTrade` in the UI, extending the previously
  backend-only deletion endpoint.

## [0.7.0] - 2026-07-22 — CSV wizard, balance history, reports, and backups

### Added

- **Cash Flow CSV wizard** (§8.1): upload, profile selection or custom setup,
  editable column mapping, row-level duplicate/error preview, and confirmation.
- **Account balance history** (`GET /accounts/{id}/history`, previously 501):
  one cumulative point per movement date, combining same-day transactions.
  Added an area chart in Reports → Net Worth.
- **Full Reports UI:** Net Worth (KPIs/history), Income Statement (monthly
  chart/table/savings rate), Expense Analysis (category pie/top expenses),
  Tax, and Backup.
- **Backup/Restore** through a new `/backup` router: on-demand creation,
  listing, download, and restore with automatic pre-restore backup. A
  dedicated UI tab requires explicit restore confirmation.
- **Tests:** ten new balance/backup/restore tests, including two regressions;
  **93 total tests, all passing**.

### Fixed — restore backup filename collision

Pre-restore backup timestamps had **second** resolution. Creating one in the
same second as the selected backup could silently overwrite the file being
restored, making restore ineffective despite apparent success. A synthetic
reproduction expected balance 1250 but observed 11249. Microsecond timestamps
fixed the collision, with a dedicated regression test.

### Fixed — test isolation

The file-backed backup/restore fixture replaced global
`app.dependency_overrides[get_db]` without restoring it. About 24 unrelated
tests after `test_backup.py` then accessed an already closed temporary database.
Saving and restoring the original override in `try/finally` fixed this recurrence
of the dependency-isolation issue described in v0.2.0.

### Security notes

- Backup download/restore strictly validates filenames against
  `pfim_backup_YYYYMMDD_HHMMSS[_ffffff].db`, preventing path traversal
  such as `../../etc/passwd`, with explicit tests.

## [0.6.0] - 2026-07-19 — Phase 5: Forecasts
### Added

- **Finance Engine projection module** (`app/finance/forecast.py`) simulates
  pessimistic/base/optimistic scenarios year by year, with independent
  compound income/expense growth, automatic or fixed monthly savings,
  extraordinary contributions in the correct year, automatic net-worth
  milestones, and eight unit tests including hand-checked calculations.
- **Scenario CRUD** (`/forecasts/scenarios`), **execution**
  (`/forecasts/run/{id}`), and **comparison** (`/forecasts/compare`).
- **Automatic starting-net-worth resolution** reads actual account balances
  and portfolio value **separately**; only the portfolio earns simulated returns.
- **Frontend:** Forecasts page with scenario creation and an area chart
  showing optimistic/base/pessimistic bands.
- **Tests:** six new forecast integration tests; **86 total tests, all passing**.

### Changed

- **Sales cannot be updated:** `PUT /trades/{id}` returns 409 for
  `type=="sell"`, requiring deletion and recreation because generated tax
  events could not be reliably recalculated on update. Purchases remained
  editable at this release, with FIFO validation now always applied.

### Explicit model assumptions

These clarify specification §10.2 and are also documented in code comments.

- Uninvested cash earns no interest in v1.0.
- Negative annual cash flow reduces cash without automatically selling
  portfolio assets to cover the deficit.
- `expected_annual_return` is total return including dividends. Separately
  distributed, non-reinvested dividends would require an explicit
  `dividend_yield_annual` parameter absent from the schema.
- Explicit numeric `starting_net_worth`, rather than auto, is treated
  entirely as starting cash because one number cannot imply its allocation
  between cash and investments.

### Roadmap status

All five phases in specification §14 are complete. At this release,
possible future work included a transaction CSV UI wizard, account balance
history, full report screens, and UI backup/restore; these are documented
in subsequent releases above.

## [0.5.1] - 2026-07-19

### Changed

- **Sales (`type: "sell"`) cannot be updated:** `PUT /trades/{id}` returns
  `409 CONFLICT` with instructions to delete and recreate. Generated capital
  gain/loss events were not reliably recalculated on update, as noted in
  v0.5.0, so blocking updates prevents inconsistent tax data.
- **Purchases remain editable**, with FIFO validation after every update.
  Reducing a purchase already consumed by a later sale now produces 409
  rather than silent inconsistency.
- Three integration tests cover blocked sale updates, allowed purchase
  updates, and FIFO-breaking purchase changes; **71 tests, all passing**.

## [0.5.0] - 2026-07-14 — Phase 4: Tax and advanced reports

### Added

- **`tax_settings`**, the twelfth table, supports configurable rates (§11.3)
  with technical defaults: capital gains 26%, Italian/US dividend withholding
  26%/15%, and securities stamp duty 0.2%, through `/tax-settings`.
- **`/tax-events`** provides an editable tax register (§11.1) for free-form entries.
- **Automatic capital gains/losses:** each security sale generates a
  `capital_gain`/`capital_loss` event using the configured rate; deleting
  the trade removes its event.
- **`/reports/tax-register`** includes gains, losses, offset net amount,
  estimated tax, dividend withholding, event detail, and the disclaimer
  required by §11.4.
- **CSV exports** through `format=csv` for net worth, income statement,
  spending analysis, and tax register (§6.8, §8.4).
- **Frontend:** editable tax rates in Settings and tax-register Report page.
- **Tests:** eight tax-events/settings tests and three currency regressions;
  **68 total tests, all passing**.

### Fixed — multiple-currency correctness (§9.8)

Aggregations summed currencies **without conversion**, implicitly treating
USD 1 as EUR 1:

- `PortfolioService.get_summary()` summed native-currency
  `PositionRead.current_value` across currencies for invested/current totals.
- `PerformanceService.portfolio_performance()` had the same problem;
  `security_performance()` additionally divided EUR income by native cost
  for Yield on Cost and Current Yield.
- `TradeService` generated tax events from native `realized_gain_loss`
  instead of EUR.

Added Finance Engine `calculate_position_eur()`, using `trade.price_eur`
instead of `trade.price`, wherever multiple securities are aggregated.
A USD −500 loss at rate 0.92 now correctly appears as EUR −460 instead of
−500. Three dedicated regressions in `test_multicurrency.py` protect this.

### Design notes

- At this release, updating a sale did not recalculate its automatic tax
  event; correcting it required deletion and recreation.
- The register offsets gains/losses **only within the requested period**.
  Multiyear loss carryforward is outside v1.0's scope.

## [0.4.1] - 2026-07-12

### Fixed

- **Windows CSV imports:** PowerShell `Out-File -Encoding utf8` can prefix
  a UTF-8 BOM. Plain UTF-8 decoding attached it to the first header
  (`date` became `\ufeffdate`), causing silent zero-row imports. All four
  CSV entry points—transaction import/preview, prices, and FX rates—now
  use `utf-8-sig`, supporting files with or without BOM.
- Added an integration test reproducing PowerShell's file format.

## [0.4.0] - 2026-07-12 — Phase 3: Returns and analysis

### Added

- **Finance Engine return metrics** in `app/finance/returns.py` and
  `app/finance/income.py`, each with dedicated unit tests: Simple Return,
  Total Return (§9.2, §9.5), TWR, MWR/XIRR, Yield on Cost, and Current Yield
  (§9.6, §9.7).
- **TWR** splits at cash flows and isolates investment return: two 10%
  subperiods compound to 21% regardless of the intermediate contribution.
- **MWR/XIRR** uses bisection with actual dates rather than
  `numpy_financial.irr`, which assumes regular periods.
- **`/performance/{security_id}`** and **`/performance/portfolio`** calculate
  metrics from trades, dividends, and current prices.
- **Reports:** `/reports/net-worth`, `/reports/income-statement` with monthly
  savings rates, and `/reports/spending-analysis` with category breakdowns
  and Top 10 lists.
- **Frontend:** Dashboard with four KPIs—net worth, account balances,
  portfolio value, and unrealized gain/loss—and Recharts monthly cash-flow
  and allocation charts.
- **Tests:** 22 new cases, 12 returns, four income, and six performance/report
  integration tests; **59 total tests, all passing**.

### Design notes

- At this release, `/reports/portfolio-performance` aliases
  `/performance/portfolio` as specified.
- `/reports/tax-register` remained 501 pending Phase 4 and configurable taxes.
- YoC/Current Yield use **last-12-month** net receipts as an annualized-income
  proxy, without extrapolating a single quarterly/semiannual payment. More
  precise extrapolation would require security coupon/dividend frequency.

## [0.3.0] - 2026-07-11 — Phase 2: Portfolio

### Added

- **Finance Engine FIFO** (`app/finance/portfolio.py`) with **100% coverage**
  across nine tests: single/multiple buys, partial/multiple-lot/full sales,
  overselling, unknown trade types, input-independent chronological ordering,
  and empty lists.
- **Security CRUD** (`/securities`) with duplicate ticker/ISIN checks.
- **Trade CRUD** (`/trades`) with **FIFO validation**, rejecting short sales
  on create/update and deletion of purchases needed by later sales (409).
- **Trade costs** (`/trades/{id}/costs`) for commissions, taxes, and similar charges.
- **Price CSV imports** (`/prices/import`) matching ticker or ISIN.
- **Exchange-rate CSV imports** (`/fx-rates/import`) with automatic reciprocal
  calculation when only one direction is supplied (§8.3).
- **Income events** (`/income-events`) with CRUD, per-security summary,
  EUR normalization, and net-after-withholding calculation.
- **Portfolio positions** (`/portfolio`) with FIFO/latest-price valuation,
  realized and unrealized gains/losses, and allocation by security type.
- **Frontend:** Portfolio KPIs/table, buy/sell form, and quick security creation.
- **Tests:** integration coverage for these flows and nine FIFO unit tests
  replacing placeholders; **37 total tests, all passing**.

### Design note

Candidate-sale FIFO validation uses a lightweight `_CandidateTrade` rather
than assigning a manual ID to an unsaved ORM `Trade`, avoiding collisions
with autoincrement on insertion.

## [0.2.1] - 2026-07-05

### Added

- `scripts/setup-code-signing.ps1` creates a local self-signed code-signing
  certificate and trusts it for the current Windows user, as a one-time setup.
- `scripts/sign-all.ps1` signs the scripts with that local certificate after
  changes, allowing `RemoteSigned` to accept files marked as downloaded.
- Dedicated instructions in `docs/setup.md`.

## [0.2.0] - 2026-07-05 — Phase 1: Foundations

### Added

- **Complete database schema:** all eleven ORM models with actual columns,
  replacing placeholders.
- **Real Alembic migrations** for the complete schema. The public source
  keeps the category catalog empty so users create their own categories.
- **Account, category, and transaction CRUD** through repository/service/router layers.
- **Configurable transaction CSV imports:** delimiter, date format, column
  mapping, decimal separator, and SHA-256 deduplication.
- **Structured errors** (§3.3): `PFIMError` subclasses and FastAPI handlers
  consistently produce `{error_code, message, detail}`.
- **Transaction currency normalization:** rate/EUR amount calculated from
  `fx_rates`, with EUR fixed at 1:1 and other currencies requiring imported rates.
- **Frontend:** functional Cash Flow table, filters, form, pagination, and
  deletion; basic account/category management in Settings.
- **Tests:** eighteen integration/unit tests covering CRUD, 400/404/409 errors,
  deduplication, pagination, and balances, all passing.

### Fixed

- SQLite relative paths were resolved against the process working directory
  instead of `backend/`, causing opening errors when launched elsewhere.
  `app/database.py` and `migrations/env.py` now resolve against project location.
- Three integration modules independently overwrote global `get_db`
  dependencies, letting the last import affect all tests. Consolidated into
  one shared fixture in `conftest.py`.

### Design note

`POST /transactions/import/preview` uses POST instead of the summary table's
GET because it receives a multipart CSV body, which GET does not standardize.

## [0.1.2] - 2026-07-05

### Fixed

- **Security:** resolved five npm vulnerabilities (one critical, one high,
  three moderate) associated with Vite ≤6.4.2/esbuild development servers by
  using Vite 7.3.6, `@vitejs/plugin-react` 4.7.0, and Vitest 4.1.9. This
  combination was checked for compatibility; a forced audit upgrade to Vite
  8.x broke the React plugin.
- Added missing `frontend/src/vite-env.d.ts`, fixing TypeScript's
  `Property 'env' does not exist on type 'ImportMeta'` build error.
- Added `frontend/package-lock.json` to pin dependency versions.

### Verified

- Clean `npm install`, zero vulnerabilities reported by `npm audit` at validation.
- Successful development startup and production build.

## [0.1.1] - 2026-07-05

### Added

- PowerShell equivalents of Makefile targets in `scripts/*.ps1`: setup,
  backend/frontend development, backend tests, migration creation/application,
  lint, and backup.
- Windows without Make instructions in `docs/setup.md`.

## [0.1.0] - 2026-07-04

### Added

- Complete backend (FastAPI, SQLAlchemy, Alembic) and frontend
  (React, TypeScript, Vite, Tailwind) directory structure.
- Working Alembic configuration with autogeneration tested against the
  placeholder schema.
- Startable FastAPI app with a real health check and 501 responses from
  other declared endpoints.
- Startable React app with sidebar and routing across eight placeholder pages.
- Finance Engine function signatures based on §9, with unimplemented bodies.
- One real health-check integration test and two placeholder finance unit tests.
- Initial ADRs and basic documentation.

### Planned next patches at this release

- Phase 1: full ORM models, Pydantic schemas, transaction/account/category
  CRUD, and the first real migration.
- Phase 2: FIFO, price/rate imports, and income management.
- Phase 3: TWR/MWR/Total Return and Dashboard KPIs.
- Phase 4: trade costs, tax events, and advanced reports.
- Phase 5: forecasts, refinement, and optimization.
