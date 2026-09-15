# Technical Risk Register

This register describes the repository's technical safeguards and regression
coverage. It does not establish the revision, migration status or compatibility
of any deployed database. Testing with existing financial data requires a
separate, explicitly authorized copy. Changes to an operational database
require specific authorization, quiescence, a verified backup and checks
before and after the operation.

PFIM is a local, single-user application that supports one backend listening
on `127.0.0.1`. This reduces exposure but does not eliminate concurrency:
the browser can issue multiple requests, and SQLite must still serialize
separate sessions and writers.

## Reading the Statuses

- **CLOSED**: the identified consequences are prevented or made explicit
  within the supported scope, with regression tests. This does not mean zero
  risk.
- **CLOSED IN THE REPOSITORY**: code, contracts and dedicated tests cover the
  supported scope; operational responsibilities or checks remain outside the
  repository.
- **CONTAINED**: the unsafe path is disabled and fails closed, but a safe
  replacement is not yet available.
- **PARTIAL**: mitigation covers only one platform or part of the declared
  scope.

Priorities retain their original meaning: **P0** for data protection or
recovery, **P1** for financial correctness and reliability, and **P2** for
hardening and reproducibility.

## Verification Coverage

- Static checks cover the backend, frontend, migrations, scripts and
  documentation.
- Backend and frontend suites are accompanied by Black, isort, Ruff, ESLint,
  TypeScript checks, a Vite build and dependency consistency checks.
- Migration and backup tests use isolated temporary files. SQLite concurrency
  tests use separate connections.
- Restore tests cover the maintenance gate, interprocess locks, idempotency,
  the offline CLI, fault injection and actual process termination at commit
  boundaries.
- Ordinary fixtures use SQLite in memory; backup, restore, migration and
  concurrency fixtures use temporary test files exclusively.
- Synthetic-data regressions cover the additional A01–A20 cases described
  below, including full backend and frontend integration paths.

Test results apply to the code revision and environment in which they run.
They do not establish the condition of an operational database. Run the
relevant checks again after changes rather than treating a historical test
count as a fixed requirement or a current verification result.

## Overview

R-01–R-16 identify the principal technical risks. Their closure does not
automatically close the distinct A01–A20 cases; the additional mitigation
table complements this register.

| ID | Status | Priority | Current mitigation | Main residual risk |
|---|---|---:|---|---|
| R-01 | CLOSED IN THE REPOSITORY | P0 | Opt-in restore with a gate, OS locks, journal and startup recovery | Operational availability, copies on separate storage and manual intervention when recovery is not deterministic |
| R-02 | CLOSED IN THE REPOSITORY | P0 | Verified online snapshot, hash and manifest | Copies on separate storage remain an operational responsibility |
| R-03 | CLOSED | P1 | Loopback, Host/Origin checks and a capability on every mutation | Does not protect against a malicious local process and is not authentication |
| R-04 | CLOSED | P1 | Explicit transactions, `BEGIN IMMEDIATE` and busy handling | SQLite remains single-writer and may report contention explicitly |
| R-05 | CLOSED | P1 | Point-in-time cutoff and metadata/warnings for FIFO fallback | Without a price, value remains an explicitly declared estimate |
| R-06 | CLOSED FOR THE V1 MODEL | P1 | One lifecycle interval and frozen cash origin | Multiple opening/closing intervals cannot be represented |
| R-07 | CLOSED | P1 | Explicit tax-event ownership and protected deletion | `legacy_unknown` rows require a human decision |
| R-08 | CLOSED | P1 | Validators, separate quoted price and ownership of automatic prices | Economic reliability still depends on the source and user review; legacy orphans require individual review |
| R-09 | CLOSED | P1 | Named bases and metadata for each metric | Recurring costs are not allocated to individual securities |
| R-10 | CLOSED | P1 | Complete batched keyset scan | Large datasets may take longer, without truncating results |
| R-11 | CLOSED | P2 | Byte/row limits, structured errors and paginated preview | Accepted files are still materialized, within declared limits |
| R-12 | CLOSED | P2 | Inactive securities are read-only; open positions block deactivation | Active/inactive status remains intentionally simple |
| R-13 | CLOSED ON WINDOWS / PARTIAL ON POSIX | P2 | Windows lock with hashes and `npm ci` | Python locks with hashes specific to each POSIX platform are missing |
| R-14 | CLOSED | P1 | Read-only Alembic-head guard before serving requests | Upgrades remain manual, authorized operations |
| R-15 | CLOSED | P1 | One effective period and daily average bases in the costs report | Tax estimates remain informational and simplified |
| R-16 | CLOSED | P1 | Canonical form and SQLite-safe limits before calculations and persistence | Application scales remain intentionally finite: 6/8/4 decimal places |

## Additional Cases and Mitigations

**A01–A06: CLOSED IN THE REPOSITORY, P1**, with dedicated regression coverage.

| ID | Priority | Mitigation |
|---|---|---|
| A01 | P1 | CORS on security and maintenance responses; readable capability renewal limited to one retry |
| A02 | P1 | Immutable CSV import snapshot, invalidation and protection against stale responses and duplicate confirmation |
| A03 | P1 | Running quantities per investment account/security, including future dates, checked before sales or purchase deletion |
| A04 | P1 | TWR includes income and costs in the pre-flow value, with consistent opening treatment and independent modes |
| A05 | P1 | XIRR requires at least two dates with nonzero net flows and opposite signs |
| A06 | P1 | Labels and net coupon amounts use the selected currency, with EUR conversion shown separately |

**A07–A20: CLOSED IN THE REPOSITORY, P2**, with dedicated contracts and
regression coverage.

| ID | Applied mitigation |
|---|---|
| A07 | UI labels and actions follow `origin`; manual/legacy entries can be explicitly unlinked, while automatic entries are protected |
| A08 | Quantities per investment account as of today, historical deficits and future trades/income block deactivation |
| A09 | Global `strip().casefold()` key, explicit ambiguity, automatic categories with the correct type and leaf status, and rollback of compound operations |
| A10 | Shared security create/update constraints, distinction between omission and null, and preserved legacy reads |
| A11 | Controlled malformed cells/headers, one commit for valid rows, global rollback and FX errors by row/column |
| A12 | Price simulation before pagination by security/date; last valid row wins and annotations describe the final result |
| A13 | Independent trailing query over `[today−364, today]` in EUR and FIFO cost at the same cutoff; KPIs remain visible with an empty selected period |
| A14 | Contributions in `(previous anniversary, current anniversary]`, excluding the base date and handling leap years correctly |
| A15 | ID-based series keys and disambiguated legends; no points outside each horizon |
| A16 | Finite starting amounts or `auto`; legacy JSON revalidated before execution and comparison |
| A17 | Numeric errors produce a `null` annualized metric without losing the rest of the report |
| A18 | Historical `cash_account_id` references participate in account blockers and future-event checks |
| A19 | Isolated, shared manifest verification; invalid entries remain visible with a reason, while download and restore are blocked |
| A20 | Monotonic copy deadline, `BACKUP_TIMEOUT`, clean staging and failure of the pre-restore backup before any swap |

## R-01 — Live Restore

**Status: CLOSED IN THE REPOSITORY — P0.**

### Scenario and Consequences

Replacing a SQLite file while connections or writes exist can leave a partial
database, mismatched sidecars or a schema incompatible with the code. Calling
`engine.dispose()` alone does not guarantee that checked-out connections have
become quiescent; progressively copying over the operational file is not an
atomic commit.

The old raw-copy path has been removed. Application recovery must avoid a
window in which a crash, concurrent requests or a second process could leave
mixed state.

### Mitigation and Evidence

- Restore is disabled by default and requires `RESTORE_ENABLED`, enabled
  backups and the expected Alembic revision together. The API exposes its
  effective state.
- The maintenance gate blocks new requests and waits for active requests to
  finish. The instance lock excludes a second backend or the offline CLI,
  while the operation lock serializes backup, restore and recovery.
- The candidate must be an immutable modern backup with a manifest, valid
  header, integrity and foreign keys, a confirmed hash and the exact revision
  expected by the build. A new verified backup of the current database is
  created before the swap.
- Staging and rollback files reside on the same filesystem. The durable
  `.pfim-restore.json` journal records `prepared`, `live_moved` and
  `committed`; recovery rolls back before commit and rolls forward after
  commit.
- Recovery runs under a lock before the schema guard. Ambiguous or tampered
  state fails closed without removing the journal or files useful for
  diagnosis.
- `request_id` and operation records make retries observable and idempotent;
  the API and `scripts/restore.ps1` share the same service.
- Dedicated tests cover eligibility, server-side confirmation, idempotency,
  backend/CLI locks, checkpointing and sidecars, fault injection at every
  journal boundary, actual process termination and a second idempotent
  recovery, using temporary databases.

### Residual Risk and Reopening Criteria

The repository cannot guarantee a copy on separate storage, prevent antivirus
or synchronization tools from holding file handles, or automatically resolve
a tampered journal or rollback file. In these cases, the protocol preserves
files and reports unavailability rather than making a heuristic choice.

The CLI can recover a pending journal before the schema guard, but it is not
a disaster-recovery path for an already corrupt or incompatible live
database: starting a new operation still requires verifying that database and
creating the mandatory pre-restore backup. Recovery from such an incident
remains an external procedure on isolated copies with a human decision.

The reproducible reference environment is Windows AMD64/Python 3.14; POSIX
remains best-effort. Reopen R-01 if any surface bypasses the gate or locks,
accepts unverified backups or different revisions, modifies the original
candidate, serves requests before startup recovery, or breaks the rule of
rollback before commit and roll-forward after commit. The full decision is in
[ADR 006](../ADR/006-restore-sqlite-crash-safe.md).

## R-02 — Consistent Backup

**Status: CLOSED IN THE REPOSITORY — P0.**

### Scenario and Consequences

A raw copy of only the `.db` file during a write can be partial or omit
commits still in the WAL. An incomplete file visible in the catalog creates
false confidence and may be discovered to be unusable only during an
incident.

### Mitigation and Evidence

- The service opens the source read-only and uses
  `sqlite3.Connection.backup()`, the SQLite Online Backup API.
- The destination starts with a unique `.partial` name; the final filename
  is not visible during the copy.
- Before publication, the service verifies `integrity_check`, foreign keys
  and the expected Alembic revision, then calculates SHA-256, size and the
  manifest.
- The file and manifest are synchronized; the manifest is promoted first,
  and the final database acts as the commit marker.
- A modern backup that has been tampered with or has an inconsistent
  manifest cannot be downloaded. Legacy backups without a manifest are
  explicitly identified as unverified.
- Simultaneous backups in the same process are serialized and use unique
  names; strictly recognizable staging and orphan files are cleaned up
  without touching unrelated files.
- `make backup` and `scripts/backup.ps1` delegate to the same verified
  service as the API.
- Dedicated tests cover an uncheckpointed WAL, DELETE journal mode with a
  concurrent commit, revision mismatches, broken foreign keys, validation
  and publication faults, concurrency, tampering and manifests.

### Residual Risk and Operational Criteria

The repository cannot guarantee that someone actually copies backups and
manifests away from the local disk. Drive failure, theft or ransomware can
therefore affect both data and local copies.

Operational mitigation requires retaining the `.db` + `.manifest.json` pair
on at least one separate, protected storage medium and periodically checking
hashes and readability on an isolated copy. This residual risk does not
reopen the backup implementation, but remains an explicit operational
responsibility.

## R-03 — Local HTTP Boundary and Drive-By Requests

**Status: CLOSED — P1.**

### Scenario and Consequences

CORS alone limits response reading, but does not guarantee that a hostile
page cannot send a request. Without a server-side secret, a page open in the
browser could create operations, change data or consume storage through
repeated backups.

### Mitigation and Evidence

- All development scripts start the backend on `127.0.0.1`.
- `TrustedHostMiddleware` accepts only configured loopback hosts.
- Middleware rejects disallowed `Origin` values and `Origin: null` on
  mutations.
- Every `POST`, `PUT`, `PATCH` and `DELETE`, with or without `Origin`,
  requires a valid `X-PFIM-Capability` before reaching the handler.
- The token contains 256 random bits, exists only in memory and changes on
  every restart. The `GET /api/v1/security/capability` bootstrap is
  `no-store` and rejects cross-origin browser readers.
- The frontend acquires the token, reuses it and renews it when the
  capability is no longer valid. OpenAPI marks all mutations with the API
  key scheme.
- `test_http_security.py` covers hostile/null origins, untrusted hosts,
  missing or incorrect tokens, valid browser and CLI clients, CORS and
  prevention of service invocation in negative cases.

### Residual Risk

The capability is not a login and does not protect against a malicious local
process that can call the bootstrap directly. Reads do not require a token.
This design is consistent only with the single-user, loopback profile:
exposing PFIM on a LAN or the Internet would require a different
authentication and authorization model and reopen R-03.

## R-04 — SQLite Transactions and Concurrency

**Status: CLOSED — P1.**

### Scenario and Consequences

Check-then-write invariants for FIFO, leaf categories, deduplication and total
sale costs fail if two writers read the same state and both write. Reads
involving multiple queries without a real transaction can also assemble a
report from different snapshots.

### Mitigation and Evidence

- Implicit `sqlite3` transaction control is disabled, and each session opens
  a transaction explicitly.
- Reads use `BEGIN`; mutations acquire `BEGIN IMMEDIATE` before aggregate
  checks, serializing writers even across separate connections.
- `get_db` is the only commit boundary: repositories and services call
  `flush`, while any exception rolls back the entire request.
- Foreign keys and a configurable `busy_timeout` are applied to every
  connection.
- `SQLITE_BUSY` and `SQLITE_LOCKED` become structured
  `DATABASE_BUSY`/`DATABASE_LOCKED` errors with status 503; non-idempotent
  mutations are not retried automatically.
- File-based tests verify configuration, concurrent writers, snapshots
  across multiple queries, leaf categories, aggregate costs, deduplication
  and competing FIFO sales. In the FIFO case, only one writer consumes the
  lot and the second is rejected without partial trades or cash flows.

### Residual Risk

SQLite remains a single-writer database. Concurrent load can cause waiting
or an explicit 503; closure guarantees correctness and rollback, not
unlimited throughput. Running multiple backends simultaneously remains
outside the supported operational profile.

## R-05 — Point-in-Time Net Worth

**Status: CLOSED — P1.**

### Scenario and Consequences

Using later positions or prices in a historical snapshot creates look-ahead
bias: a security can appear before purchase, disappear before sale or be
valued using future information.

### Mitigation and Evidence

- Reports, portfolio and performance apply a common cutoff: trades and
  prices must be no later than the requested date; current views ignore
  future rows.
- Latest-price endpoints also apply today's cutoff: future rows remain in
  administrative history but are not labeled as current quotes in
  Securities.
- `net-worth` rejects a future `as_of_date` and correctly includes same-day
  operations.
- Individual snapshots and history use the same `portfolio_value_series`
  valuation.
- If no valid price exists by the date, the position remains included at
  FIFO cost. The response exposes `portfolio_valuation.cost_fallback_used`
  and the list of affected securities.
- Portfolio, summary, Securities Analysis and aggregate performance apply
  the same rule and declare `valuation_source='fifo_cost'`; Dashboard,
  Net Worth and reports show an explicit warning. Metrics for an individual
  security that truly require a price remain `null`.
- `test_point_in_time_reports.py`, `test_performance_contract.py` and the
  frontend `portfolioValuation` tests cover cutoffs, future dates, fallback
  and warnings.

### Residual Risk

FIFO cost is not a market quote. The number can differ substantially from
realizable value, but is no longer silently presented as a price. Entering
reliable historical quotes remains the way to remove the estimate for the
affected periods.

## R-06 — Account Lifecycle and Historical Cash Account

**Status: CLOSED FOR THE SINGLE-INTERVAL V1 MODEL — P1.**

### Scenario and Consequences

An archived account that disappears retroactively, receives new writes or
moves historical cash flows when its reference changes alters balances,
net worth and forecasts. An investment account with its own opening balance
can also double count cash and portfolio value.

### Mitigation and Evidence

- Constraints require investment accounts to have a zero opening balance
  and a reference account; non-investment accounts cannot have a reference.
- The reference must exist, be a non-investment account, be active and
  already be open on the investment account's opening date. Its deactivation
  is blocked while it serves an active investment account.
- Account deactivation requires a zero balance and no operational
  dependencies, open positions or future financial sources.
- `opened_on` and `closed_on` define inclusive bounds. New accounts start
  today unless an explicit past date is provided; future dates are rejected.
- Manual/imported transactions, transfers, trades, income, recurring costs
  and their cash flows verify that the account is active and exists on the
  economic date.
- An inactive account is read-only history: it accepts neither new writes
  nor deletions that would alter its historical balance.
- A closure performed today can be reversed on the same day. Reactivation
  cannot erase a historical closure: a new account is required for the new
  interval.
- `cash_account_id` is frozen on trades, income and costs. Changing the
  reference account is prospective and does not move previously generated
  transactions; even a zero-net cash flow retains its origin.
- Type and opening balance cannot be changed once financial history exists;
  hard deletion aggregates all financial blockers and does not use
  destructive cascades from accounts.
- Migrations `f2b6d8a4c1e9`, `a4c7e9b2d5f8` and the migration that freezes
  cash origin fail closed on ambiguous legacy states instead of inventing
  references or dates.
- Lifecycle, temporal and migration tests cover dated writes, deactivation,
  deletion on read-only accounts, historical reactivation and prospective
  references.

### Intentional Residual Limitation

V1 represents one `[opened_on, closed_on]` interval. It cannot describe
closure, reopening and another closure of the same account. This is a
declared limitation: after a historical closure, create a new account
record. If the product requires multiple intervals, it will need a table of
effective-dated periods, and R-06 must be reopened.

For legacy records with `NULL` dates, that bound is intentionally unknown,
and the account remains present in historical snapshots. Any backfill must
follow a decision about the data, never an automatic heuristic.

## R-07 — Tax-Event Ownership and Deletion

**Status: CLOSED — P1.**

### Scenario and Consequences

Without explicit ownership, a manual event linked to a trade can be mistaken
for an automatic event and rewritten or deleted by synchronization.
Multiple or duplicate links can cause tax double counting.

### Mitigation and Evidence

- `tax_events.origin` distinguishes `manual`, `automatic_trade` and
  `legacy_unknown`.
- CHECK constraints and a partial unique index enforce a single source and
  at most one automatic event per sale; an automatic event requires a trade.
- User input always creates manual rows. Automatic rows cannot be edited or
  deleted directly.
- FIFO synchronization updates or deletes only `automatic_trade` rows;
  compatible manual notes and flags survive realignment.
- Deleting a source removes only derived records owned by the service;
  manual or legacy references block the operation with an explicit conflict.
- Migration `d4e8f2a6c1b9` classifies only unambiguous cases and stops before
  changing the schema if links require a decision.
- `test_tax_event_origin_migration.py` and
  `test_fiscal_register_follows_fifo.py` cover backfill, ambiguity,
  realignment and preservation of manual events.

### Residual Risk

`legacy_unknown` is deliberately conservative: it prevents the system from
assuming ownership, but requires human review before some deletions. Tax
estimates are also informational and do not replace tax documents or advice;
this limitation is separate from ownership correctness.

## R-08 — Prices, Exchange Rates and Preview/Import Consistency

**Status: CLOSED — P1.**

### Scenario and Consequences

Zero, negative, nonfinite or out-of-precision prices and rates contaminate
net worth, returns and conversions. A preview that differs from import
makes user confirmation unreliable; a stale automatic reciprocal can
produce inconsistent conversions. Confusing settlement price and quoted
price also alters native FIFO; without ownership, deleting a trade can
leave an orphan automatic price or delete a manual observation.

### Mitigation and Evidence

- Manual entry, preview and import share Decimal validation: values must be
  finite, strictly positive and within column limits.
- SQLite CHECK constraints protect `price_close`, `price_close_eur`,
  `prices.fx_rate` and `fx_rates.rate` even outside the API.
- Price preview and import share parsing, matching, errors and the
  insert/update decision on `(security_id, date)`. Structural and numeric
  errors take the same precedence over an unknown ticker in both flows.
- System-generated reciprocals have origin `csv_import_reciprocal` and
  update with the direct rate; an explicit direction is not overwritten.
  Inconsistent explicit pairs are rejected independently of CSV row order.
- Migration `e7b3c9a5d1f4` checks for incompatible data first and does not
  correct it automatically.
- `trades.quote_price` is distinct from settlement price. It is required
  when currencies differ and must be consistent when they match or the
  security is quoted in EUR; native and historical FIFO use the correct
  field.
- `prices.origin_trade_id`, CHECK, UNIQUE and a cascading foreign key make
  ownership explicit. Deletion, reassignment and manual/CSV overrides affect
  only the provenance they are authorized to manage.
- Migration `d7b2e9f4a6c1` prechecks legacy trades before DDL and retains
  prices that cannot be attributed with certainty as `legacy_trade_orphan`.
  It does not infer that data should be deleted.
- `test_import_hardening.py`, `test_trade_quote_prices.py` and
  `test_trade_quote_price_migration.py` cover numeric domains,
  preview/import parity, cross-currency trades, ownership, overrides and
  precheck atomicity.

### Residual Risk

Constraints verify shape and numeric domain, not the economic reliability
of the source. A positive price attached to the wrong ticker or date can
still appear plausible to the database: preview, provenance and user review
remain necessary.

Legacy orphan prices must remain preserved by the migration and be reviewed
individually. Any correction requires an explicit decision about the affected
data; the ownership model does not authorize heuristic deletion.

## R-09 — Performance Metric Bases

**Status: CLOSED — P1.**

### Scenario and Consequences

The former `gross` boolean could produce metrics on different, undeclared
bases in the same response, making total return, yield, MWR and TWR
impossible to compare reliably.

### Mitigation and Evidence

- The contract uses named axes: `income_basis=net|gross` and
  `cost_basis=exclude|include`.
- Each response includes `metadata` with requested bases, the scope of trade
  and recurring costs, and `metric_bases` for each indicator.
- Total return, MWR and TWR consistently apply the selected bases; yield and
  income use the declared net/gross basis. Metrics independent of an axis
  state that in their metadata.
- `gross` remains only as a deprecated alias, and a conflict with
  `income_basis` is rejected.
- The contract distinguishes the portfolio, where recurring costs can be
  included, from an individual security, where they are
  `not_allocated_to_security`.
- `test_performance_contract.py` verifies named bases, the legacy alias,
  conflicts, consistency for security/portfolio scope and future-row cutoffs.

### Residual Risk

Recurring portfolio costs have no allocation by security; PFIM does not
invent a distribution. Metadata declares the limitation, which can be
removed only by introducing an explicit domain allocation rule.

## R-10 — Completeness Beyond 100,000 Transactions

**Status: CLOSED — P1.**

### Scenario and Consequences

Loading a single page of 100,000 rows could silently truncate summaries,
reports and exports, especially omitting older transactions.

### Mitigation and Evidence

- `TransactionRepository.iter_filtered()` traverses every filtered row in
  batches of 2,000 using keyset pagination on the ID.
- Summary, income statement, category analysis, average expenses and export
  use the complete iterator instead of an arbitrary page.
- `test_report_completeness.py` simulates multiple batches beyond the former
  boundary and verifies that every row contributes to totals.

### Residual Risk

A complete scan can require more queries and time on very large archives,
but memory per batch is bounded and incomplete results are no longer
published. Future SQL optimizations must preserve the same completeness
property.

## R-11 — CSV Uploads and Preview

**Status: CLOSED — P2.**

### Scenario and Consequences

Unlimited uploads or whole-file `read()` calls can exhaust memory; unhandled
invalid encodings, CSV content or delimiters can produce 500 responses. A
huge preview can also stall both browser and backend.

### Mitigation and Evidence

- Uploads are read in 64 KiB chunks and rejected above the configured limit,
  5 MiB by default, without trusting `Content-Length`.
- Parsing stops beyond 100,000 rows.
- Invalid UTF-8, delimiters other than one non-newline character,
  `csv.Error` and invalid numeric values become structured PFIM errors;
  exceeding limits returns 413 `PAYLOAD_TOO_LARGE` without writes.
- Transaction and price previews return 200 rows by default, at most 500,
  while retaining global counts of rows, errors, duplicates and
  inserts/updates.
- The price wizard associates each asynchronous response with the latest
  request: changing file or page invalidates the preceding response, so it
  cannot display file A and confirm file B. A successful import invalidates
  prices, portfolio, performance and reports through a shared rule.
- `test_import_hardening.py` covers bytes, encoding, rows, delimiters,
  pagination and the absence of writes on failure.

### Residual Risk

Parsing an accepted file does not stream end to end: content and rows are
materialized for validation and global counts. Consumption is bounded by
the declared byte and row limits. Reassess R-11 before substantially
increasing those limits.

## R-12 — Inactive Security Lifecycle

**Status: CLOSED — P2.**

### Scenario and Consequences

An archived security that remains selectable for new writes mixes history
and active operations. Deactivating it while units are held can instead
hide a position that remains economically relevant.

### Mitigation and Evidence

- Deactivation is blocked if the open FIFO quantity is nonzero or FIFO
  history is inconsistent.
- An inactive security remains visible in history, but services and the UI
  block new trades, prices, income and additions/deletions of trade costs.
- Price preview and import flag inactive securities without writing.
- The interface supports deactivation/reactivation, and selectors for new
  writes include only active securities.
- Backend lifecycle and frontend `lifecycle` tests verify the separation
  between historical viewing and writing.

### Residual Risk

V1 uses a single flag. A security still held but no longer tradable cannot
be archived while its position remains open. Introducing distinct states
such as `tradable`, `delisted` and `archived` would require a new domain
decision; the current model neither loses nor hides data.

## R-13 — Dependency Reproducibility

**Status: CLOSED FOR REFERENCE WINDOWS / PARTIAL ON POSIX — P2.**

### Scenario and Consequences

Unlocked version ranges can install different transitive dependencies on
two setups, changing validation, transactions or migrations without a
visible repository change.

### Mitigation and Evidence

- The reference runtime is pinned to Python 3.14.6, Node.js 26.4.0 and
  npm 11.17.0 through `.python-version`, `.node-version` and `engines`.
- `backend/pylock.toml` contains versions, wheels and hashes and is
  intentionally limited to Windows AMD64 / Python 3.14.
- `scripts/setup.ps1` installs the lock with `--require-hashes`.
- `frontend/package-lock.json` is applied with `npm ci` in scripts and the
  Makefile.
- `backend/constraints-tested-win-py314.txt` documents dependency versions
  validated by the Windows suite.
- The HTTP suite uses `httpx2` 2.12, the client compatible with Starlette 1.3;
  constraints and `pylock.toml` also include `httpcore2` and `truststore`
  with deterministic wheels/hashes, avoiding the deprecated legacy adapter.
- Backend and frontend tests, lint, build and migration/backup checks use
  this reference environment.

### Residual Risk and POSIX Closure Criteria

The POSIX Makefile uses `requirements-dev.txt` constrained by the constraints
file, but does not verify wheel hashes specific to the OS and architecture.
It therefore does not offer the same reproducibility as the Windows path.

Closing POSIX coverage requires hashed locks for every combination actually
supported, CI installation from those locks and the full suite on each
platform. Otherwise, macOS/Linux must remain documented as a best-effort
development path, without claiming an equivalent reproducible build.

## R-14 — Startup with an Incompatible Schema

**Status: CLOSED — P1.**

### Scenario and Consequences

A lazy SQLAlchemy engine can complete startup without querying the schema.
Without a guard, a database at an earlier revision could leave the health
check green and return `500` only on the first queries using new columns.
The service would appear to be running while being partly unusable.

### Mitigation and Evidence

- Lifespan derives the heads from Alembic files and compares them exactly
  with the database's current heads before exposing any endpoint.
- File-based SQLite is opened with `mode=ro`; a missing path is not created.
- Mismatches, unversioned databases and read errors stop startup with the
  expected and observed revisions. There is no fallback to `upgrade`,
  `stamp` or `create_all`.
- Dedicated tests verify success, rejection, the absence of upgrades and
  preservation of hashes, timestamps and sidecars.

### Residual Risk

The guard diagnoses and blocks but intentionally does not repair. The
operator must still identify the correct target, stop the backend, create a
verified backup and apply Alembic with explicit authorization. This friction
is a safety property and must not be bypassed by automating an upgrade at
startup.

## R-15 — Temporal Consistency in the Costs Report

**Status: CLOSED — P1.**

### Scenario and Consequences

Comparing costs filtered by period against capital, portfolio value or TWR
calculated over all history or as of today produces dimensionally valid but
economically misleading percentages. Including a current stamp-duty
estimate among historical costs also creates a cost that was never incurred
in the period.

### Mitigation and Evidence

- Realized results, taxes, costs, TWR and denominators use the same inclusive
  effective interval, never beyond today. Inverted intervals and future
  start dates are rejected.
- `% of invested capital` divides by daily average FIFO cost; the annual
  cost ratio divides by daily average value and annualizes using actual
  days. Bases and duration are exposed in the response.
- Averages weight intervals between change dates without materializing every
  day. Required data is preloaded, and the SQL budget remains constant as
  the number of securities increases.
- The current stamp-duty estimate is separate from groups, totals, net
  results and ratios; tax amounts below one cent are settled using
  `ROUND_HALF_UP`.
- `test_costs_period_coherence.py` covers historical periods, weighted
  averages, separate stamp duty, rounding, invalid intervals and query
  budgets.

### Residual Risk

PFIM's tax rates and taxation remain informational estimates subject to the
limitations in §11 of `finance-calculations.md`; period consistency does not
make them certified tax calculations. For history without quotes, average
value uses the explicitly declared FIFO fallback described in R-05.

## R-16 — Representability of Persisted Amounts

**Status: CLOSED — P1.**

### Scenario and Consequences

SQLite treats `NUMERIC(18,6)` as an affinity and does not enforce precision
and scale like a strict decimal database. A nonzero amount below `0.000001`
could therefore be read back as zero and disappear from balances and
reports; a product above the maximum could be accepted by SQLite but lose
its final digit through the `binary64` bind. The same risk applies to
exchange rates at eight decimal places and percentages at four. Multiplying
an already rounded EUR unit price by large quantities also amplifies error
in FIFO and valuations. Finally, checking a trade's implied exchange rate
used to depend on automatic price creation and could be skipped when a
more authoritative price already existed on that date.

### Mitigation and Evidence

- `normalize_numeric_18_6`, `normalize_fx_rate` and `normalize_numeric_8_4`
  canonicalize with `ROUND_HALF_EVEN` to 6, 8 and 4 decimal places
  respectively before any calculation or write. Zero is distinguished from
  a nonzero input that would disappear at the declared scale.
- Application maxima are 999,999,999 for `NUMERIC(18,6)` and 9,999,999 for
  `NUMERIC(18,8)` exchange rates: more conservative than the DDL, but verified
  by a SQLite round trip at full scale. The DDL remains unchanged for
  historical compatibility.
- Shared conversion validates and returns a canonical native amount,
  exchange rate and EUR amount. Transactions, transfers, income, recurring
  costs and trade costs use it; CSV preview and confirmation apply the
  same rule.
- Opening balances, numeric bond metadata, prices, percentage costs, manual
  tax events and tax settings pass through the same guards. Configurable
  rates are also limited to 0–100%, and the gross capital-gain/loss sign
  matches the convention assumed by reports.
- `LinkedCashMovement` checks the aggregated result again before writing the
  transaction, covering cases such as purchase consideration plus fees.
- Trades validate quantity, EUR price, both totals and implied exchange
  rate before the INSERT, even when no automatic price needs to be created.
- EUR FIFO allocates authoritative `total_eur` as `total_eur / quantity`;
  valuations use `price_close × fx_rate × quantity`. Unit fields `price_eur`
  and `price_close_eur` remain informational, so their rounding is not
  amplified in totals.
- Automatic tax-event amounts are explicitly settled to cents with
  `ROUND_HALF_UP`; net amounts use the already settled value, rather than a
  fraction SQLite would round implicitly.
- Pure and integration tests cover SQLite round trips, HALF_EVEN ties,
  underflow, overflow, CSV, atomicity, balances, taxation, preexisting prices,
  tiny capital gains and large quantities with fractional prices.

### Residual Risk

Persisted scales remain six decimal places for amounts/prices/quantities,
eight for exchange rates and four for percentages/tax rates. They are not
suitable for data requiring smaller units or magnitudes beyond application
limits. Extending them requires a domain decision, driver verification and a
migration; accepting values SQLite cannot read back consistently is not an
alternative.

## Remaining Actions in Priority Order

The operational responsibilities below are separate from repository defect
fixes and do not establish the condition of any real financial data.

1. **Keep restore disabled by default** and enable it only with an explicit
   revision, hash and operational procedure.
2. **Establish copying to separate storage** for the backup/manifest pair
   and periodic verification on isolated media; this is R-02's operational
   residual risk.
3. **Exercise recovery periodically** on isolated copies, including rollback
   before commit, roll-forward after commit and restart before the schema
   guard.
4. **Define the POSIX scope**: add platform-specific locks and CI or formally
   declare it best-effort, resolving the ambiguity in R-13.
5. Rerun the full suite, migration/backup/restore selection, concurrency
   checks, lint and build after any change affecting these boundaries.

## Established Domain Decisions

- `as_of_date` means end of day, includes same-day events and cannot be in
  the future.
- Without a historical price, the position remains included at FIFO cost
  with explicit metadata and a warning.
- An inactive account is read-only history; a past closure is not erased,
  and V1 uses a single operational interval.
- Reference-account changes are prospective; historical cash flows never
  move implicitly.
- Hard deletion is permitted only without financial state or dependencies.
- Automatic tax events declare ownership; manual and legacy events are not
  rewritten heuristically.
- An inactive security remains readable but accepts no new writes;
  deactivation requires zero quantity in every investment account as of
  today, no historical deficit and no future trade or income payment.
- Restore is not ordinary CRUD: it remains opt-in and uses only ADR 006's
  crash-safe maintenance protocol or the equivalent offline CLI.

## Technical References

- [SQLite Online Backup API](https://www.sqlite.org/backup.html)
- [Python `sqlite3.Connection.backup`](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup)
- [ADR 006 — Crash-Safe SQLite Restore](../ADR/006-restore-sqlite-crash-safe.md)
- [SQLite transactions](https://www.sqlite.org/lang_transaction.html)
- [SQLite WAL](https://www.sqlite.org/wal.html)
- [SQLite PRAGMA](https://www.sqlite.org/pragma.html)
- [SQLite: How to Corrupt Your Database Files](https://www.sqlite.org/howtocorrupt.html)
- [SQLAlchemy SQLite: transaction control](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html)
- [FastAPI CORS](https://fastapi.tiangolo.com/tutorial/cors/)
- [Starlette `TrustedHostMiddleware`](https://www.starlette.io/middleware/#trustedhostmiddleware)
