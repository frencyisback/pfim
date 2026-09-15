# 📊 PFIM - Personal Finance & Investment Manager

A local desktop application for tracking personal finances and investment portfolios, and forecasting long-term net worth.

## 🎯 Main Features

- ✅ **Cash Flow Tracking**: Categorized income and expenses
- ✅ **Portfolio Management**: Purchases, sales, coupons and dividends using FIFO
- ✅ **Financial Calculations**: TWR, MWR/IRR, Total Return, Yield on Cost
- ✅ **Multiple Currencies**: Amounts entered with their currency and exchange rate, converted to euros on entry ([how it works](docs/multi-currency.md))
- ✅ **CSV Import**: Configurable imports from banks and brokers
- ✅ **Analytical Reports**: Net worth, income statement, P&L and taxes
- ✅ **Forecasts**: Net worth projection scenarios from 1 to 50 years
- ✅ **Taxes and Fees**: Flexible tracking
- ✅ **Local Core**: The application and database stay on the user's computer

PFIM is designed for a single user and binds exclusively to loopback
(`127.0.0.1`). It does not provide multi-user authentication and must not be
exposed on a LAN or the Internet. Mutating HTTP operations are protected by
a volatile capability token, but this local safeguard does not replace a
login system.

## Pages at a Glance

Start in **Settings** by creating accounts and categories. Link each investment
account to a cash account, then add your transactions and investment activity.

| Page | What to enter | What you will find |
|---|---|---|
| **Dashboard** | Automatically uses your recorded data. | Net worth, account balances, portfolio value and summary charts. |
| **Cashflow** | Income/expenses with date, account, category, amount and description; CSV imports and transfers. | Your transaction history, filtered by account, category or period. |
| **Portfolio** | Automatically uses your trades and prices. | Current holdings, invested capital, valuations and realised/unrealised gains or losses. |
| **Securities** | Security details, trades (date, account, quantity, price and fees), prices and recurring costs. | Your security catalogue, latest quotes and trading/cost history. |
| **Income** | Coupons, dividends or capital repayments: security, account, payment date, gross amount and tax withheld. | Recorded investment income and net amounts received. |
| **Reports** | Select a period; add or manage tax entries when needed. | Net worth, returns, income/spending breakdowns, costs, taxes, CSV exports and backup/restore tools. |
| **Forecasts** | Starting capital, time horizon, monthly income/expenses and growth/return assumptions. | Net worth projections and comparisons of saved scenarios. |
| **Settings** | Accounts with opening dates/balances, categories, tax rates, exchange rates and CSV mappings. | The configuration used by entry forms, imports and calculations. |

## 🏗️ Technology Stack

### Backend

- **Python 3.14.6** - Reference runtime
- **FastAPI** - API framework
- **SQLAlchemy 2.0** - ORM
- **SQLite** - Database
- **Alembic** - Schema migrations
- **Pydantic** - Data validation

Financial calculations (FIFO, TWR, XIRR and projections) are implemented
directly in `backend/app/finance/` using `Decimal`, without numerical libraries:
XIRR requires irregular dates, which `numpy_financial.irr` does not handle
(see the `money_weighted_return` docstring).

### Frontend

- **React 18** - UI framework
- **TypeScript 5** - Static typing
- **Vite 7** - Build tool
- **Tailwind CSS 3** - Styling
- **Recharts 2** - Charts
- **TanStack Query** - Server state, caching and invalidation

There is no global store: persistent application state lives on the server,
and TanStack Query keeps it synchronized. Screen-local state (filters and
open forms) lives in components through `useState`.

## 🚀 Quick Start

### Prerequisites

- Python 3.14.6
- Node.js 26.4.0
- npm 11.17.0
- A pip version that supports installation from `pylock.toml`

Versions are also pinned in `.python-version`, `.node-version` and
`frontend/package.json`. The Python lock with hashes (`backend/pylock.toml`)
targets the Windows x86-64 reference environment; for macOS/Linux, see
[Development Environment Setup](docs/setup.md).

### 1. Install Dependencies

On Windows, from the project root:

```powershell
.\scripts\setup.ps1
```

The script creates the virtual environment, installs the backend from
`pylock.toml` with hash verification, runs `npm ci`, and creates both `.env`
files from their templates if they do not exist. On macOS/Linux, use
`make install` and manually copy the `.env.example` files as described in the
setup guide.

### 2. Prepare the Development Database

The default already points to the isolated database
`sqlite:///../data/pfim-dev.db`. Before applying Alembic migrations, still
check the effective `DATABASE_URL`, then run:

```powershell
.\scripts\migrate.ps1
```

The macOS/Linux equivalent is `make migrate`. An environment variable or a
custom `.env` file can change the target: read [Data Safety](docs/data-safety.md)
first and never test a migration on real data.

A new database starts without categories or CSV import profiles. Users create
the categories and mappings they need. Recording trades, income, transfers
or security costs automatically creates the relevant English system category
when it is first needed.

### 3. Start in Development Mode

**Windows — double-click startup** (after completing steps 1 and 2 once):
double-click `start.bat` in the project directory. It opens the backend and
frontend in two windows and opens the browser at `http://localhost:5173`.
Close both windows to stop the application.

**From a terminal** (macOS/Linux, or Windows with Git Bash/WSL):

```bash
# Show instructions for both processes
make dev

# Start in two separate terminals:
make dev-backend  # Terminal 1: http://localhost:8000
make dev-frontend # Terminal 2: http://localhost:5173
```

Before accepting requests, the backend performs a read-only comparison
between the database's Alembic revision and the revision required by the code.
If they differ, startup stops and reports the expected and actual revisions;
no database is created and no migration runs automatically. Follow the
controlled procedure in [Setup](docs/setup.md#startup-schema-check), without
using `alembic stamp` or adding columns manually.

### 4. Open the Application

- **Frontend**: http://localhost:5173
- **API Docs**: http://localhost:8000/docs
- **Configured Database**: `DATABASE_URL` in `backend/.env`; the development
  default is `data/pfim-dev.db`

## 📁 Project Structure

```text
pfim/
├── backend/
│   ├── app/
│   │   ├── models/          # SQLAlchemy ORM
│   │   ├── schemas/         # Pydantic request/response
│   │   ├── repositories/    # Data access layer
│   │   ├── services/        # Business logic
│   │   ├── finance/         # Pure finance engine
│   │   ├── routers/         # FastAPI routers
│   │   ├── main.py          # Entry point
│   │   ├── config.py        # Configuration
│   │   └── database.py      # SQLAlchemy setup
│   ├── migrations/          # Alembic migrations
│   ├── tests/
│   │   ├── unit/            # Unit tests
│   │   └── integration/     # Integration tests
│   ├── pyproject.toml       # black, isort and ruff configuration
│   ├── pylock.toml          # Hash lock: Windows x86-64 / Python 3.14
│   ├── constraints-tested-win-py314.txt # Validated versions
│   ├── requirements.txt     # Declared runtime dependencies
│   └── requirements-dev.txt # Declared development dependencies
│
├── frontend/
│   ├── src/
│   │   ├── api/             # HTTP client and TanStack Query hooks
│   │   ├── components/      # Reusable components
│   │   ├── pages/           # One per navigation item
│   │   ├── lib/             # Formatters, currencies and security types
│   │   ├── App.tsx          # Layout and routes
│   │   └── main.tsx         # Entry point
│   ├── package.json         # Dependencies and required Node/npm runtimes
│   ├── package-lock.json    # npm lock used by npm ci
│   └── vite.config.ts       # Vite configuration
│
├── data/                    # Local databases and their backups
│
├── ADR/                     # Architecture Decision Records
├── docs/                    # Operating guides: setup, CSV formats, calculations
├── scripts/                 # PowerShell equivalents of Makefile commands
├── start.bat                # Double-click startup on Windows
├── Makefile                 # Development commands (Unix)
├── CHANGELOG.md             # Change history
└── README.md                # This file
```

There are two environment-variable templates, one for each side:
`backend/.env.example` and `frontend/.env.example`.

## 📚 Development Documentation

| Document | Contents |
|---|---|
| [docs/setup.md](docs/setup.md) | Installation, migrations and tests |
| [docs/data-safety.md](docs/data-safety.md) | Operating rules to protect databases and copies |
| [docs/risk-register.md](docs/risk-register.md) | Open, contained and closed risks, evidence and remaining operational issues |
| [docs/multi-currency.md](docs/multi-currency.md) | Conversion on entry |
| [docs/finance-calculations.md](docs/finance-calculations.md) | FIFO, TWR, IRR and projection implementation choices |
| [docs/csv-formats.md](docs/csv-formats.md) | Import file formats |
| [ADR/](ADR/) | Architectural decisions and their rationale |
| [technical-specification.md](technical-specification.md) | Complete functional specification |

### Finance Engine

The finance engine (`backend/app/finance/`) is a **pure** module with no side
effects and is fully testable:

```python
from datetime import date
from decimal import Decimal

from app.finance.portfolio import calculate_position_native, calculate_position_eur
from app.finance.returns import time_weighted_return

# FIFO position in the security's native currency
position = calculate_position_native(trades)
# -> Position(quantity, average_cost, total_invested, realized_gain_loss, lots)

# Use the EUR variant for EVERY aggregation across securities
position_eur = calculate_position_eur(trades)

# Realized result for EACH sale: the tax register has one row per sale.
# {trade_id: realized gain/loss}
from app.finance.portfolio import realized_by_sell_eur
realized_per_sale = realized_by_sell_eur(trades)

# Time-weighted return, removing the effect of cash flows
twr = time_weighted_return(
    starting_value=Decimal("1000"),
    ending_value=Decimal("1100"),
    cash_flows=[],
    prices_at_flow_dates={},
    period_start=date(2026, 1, 1),
    period_end=date(2026, 12, 31),
)
```

Import modules by name (`app.finance.portfolio`, `app.finance.returns`,
`app.finance.income`, `app.finance.forecast`, `app.finance.currency`,
`app.finance.periods`): the `app.finance` package does not re-export symbols,
so each function's origin remains explicit at the call site.

`app.finance.periods` keeps calendar conventions (365 days per year, 30.44 per
month) in one place. Previously, different hardcoded values made "last 12
months" mean 360 days in one calculation and 365 in another.

### Database Schema

Main tables:

- `categories` - Hierarchical expense/income categories
- `accounts` - Checking and savings accounts
- `transactions` - Income and expenses
- `securities` - Security master data
- `trades` - Buy/sell operations
- `trade_costs` - Costs associated with trades
- `prices` - Price history
- `income_events` - Dividends and coupons
- `portfolio_costs` - Recurring portfolio costs, such as stamp duty and custody
- `fx_rates` - Exchange rates
- `tax_events` - Tax register
- `tax_settings` - Configurable tax parameters
- `forecast_scenarios` - Saved forecast scenarios
- `csv_import_profiles` - Import mapping profiles

### API Endpoints

```text
GET    /api/v1/transactions
GET    /api/v1/transactions/{id}
GET    /api/v1/transactions/summary
POST   /api/v1/transactions
DELETE /api/v1/transactions/{id}
POST   /api/v1/transactions/transfer
POST   /api/v1/transactions/import/preview   # Requires account_id; preview performs no writes
POST   /api/v1/transactions/import

GET    /api/v1/accounts
POST   /api/v1/accounts
PUT    /api/v1/accounts/{id}
POST   /api/v1/accounts/{id}/deactivate
DELETE /api/v1/accounts/{id}
GET    /api/v1/accounts/{id}/balance
GET    /api/v1/accounts/{id}/history

GET    /api/v1/categories
POST   /api/v1/categories
DELETE /api/v1/categories/{id}

GET    /api/v1/securities
POST   /api/v1/securities
PUT    /api/v1/securities/{id}
DELETE /api/v1/securities/{id}

POST   /api/v1/prices
POST   /api/v1/prices/import/preview
POST   /api/v1/prices/import
GET    /api/v1/prices/latest
GET    /api/v1/prices/{security_id}
GET    /api/v1/prices/{security_id}/latest

GET    /api/v1/csv-import-profiles
POST   /api/v1/csv-import-profiles
DELETE /api/v1/csv-import-profiles/{id}

GET    /api/v1/trades
GET    /api/v1/trades/{id}
POST   /api/v1/trades
DELETE /api/v1/trades/{id}
POST   /api/v1/trades/{id}/costs
GET    /api/v1/trades/{id}/costs
DELETE /api/v1/trades/{id}/costs/{cost_id}

GET    /api/v1/portfolio
GET    /api/v1/portfolio/summary
GET    /api/v1/portfolio/{security_id}

GET    /api/v1/portfolio-costs
POST   /api/v1/portfolio-costs
DELETE /api/v1/portfolio-costs/{id}

GET    /api/v1/reports/net-worth
GET    /api/v1/reports/net-worth/history
GET    /api/v1/reports/income-statement
GET    /api/v1/reports/spending-analysis
GET    /api/v1/reports/income-analysis
GET    /api/v1/reports/transfer-analysis
GET    /api/v1/reports/securities-analysis
GET    /api/v1/reports/dividends-analysis
GET    /api/v1/reports/costs-analysis

GET    /api/v1/performance/portfolio            # TWR, MWR/IRR and total return: cumulative and annualized
GET    /api/v1/performance/{security_id}

GET    /api/v1/income-events
POST   /api/v1/income-events
DELETE /api/v1/income-events/{id}
GET    /api/v1/income-events/summary

GET    /api/v1/fx-rates
POST   /api/v1/fx-rates/import
GET    /api/v1/fx-rates/suggest              # Suggested exchange rate for a form
GET    /api/v1/fx-rates/{from}/{to}/{date}

GET    /api/v1/tax-events
POST   /api/v1/tax-events
PUT    /api/v1/tax-events/{id}
DELETE /api/v1/tax-events/{id}

GET    /api/v1/tax-settings
PUT    /api/v1/tax-settings/{key}

GET    /api/v1/forecasts/scenarios
POST   /api/v1/forecasts/scenarios
GET    /api/v1/forecasts/scenarios/{id}
DELETE /api/v1/forecasts/scenarios/{id}
POST   /api/v1/forecasts/run/{id}
POST   /api/v1/forecasts/compare

GET    /api/v1/backup
POST   /api/v1/backup
GET    /api/v1/backup/status
GET    /api/v1/backup/restore-operations/{request_id}
GET    /api/v1/backup/{filename}/download
GET    /api/v1/backup/{filename}/manifest
POST   /api/v1/backup/{filename}/restore    # Crash-safe restore, only when enabled

GET    /api/v1/security/capability

GET    /api/v1/health
```

The complete, current list is available at http://localhost:8000/docs
(OpenAPI generated by FastAPI). Every `POST`, `PUT`, `PATCH` or `DELETE`
requires the `X-PFIM-Capability` header. The frontend obtains and refreshes it
automatically through `GET /api/v1/security/capability`; in Swagger, request
it and enter it through **Authorize**. The token exists only in the process
and changes when the backend restarts.

Refreshing retries a request only once, and only after `CAPABILITY_REQUIRED`
or `CAPABILITY_INVALID`. CORS makes security and maintenance errors readable
from allowed origins. Network or maintenance errors do not trigger another
automatic write.

Backup and restore are disabled by default. Backup becomes available only
with `BACKUP_ENABLED=true` and `EXPECTED_ALEMBIC_REVISION` set to the exact
build revision. It uses the SQLite Online Backup API to take a consistent
snapshot while the application is in use. It publishes the file and its
manifest only after integrity, foreign-key, revision and SHA-256 checks.
Keep the backup database and manifest together, and copy them to separate
storage as well.

The copy loop has a configurable limit through `BACKUP_COPY_TIMEOUT_SECONDS`
(default 60 seconds, range 1 to 600). On expiry, it returns `BACKUP_TIMEOUT`
without publishing the new copy. The limit covers the SQLite loop, not the
entire procedure including validation and fsync. A malformed manifest remains
flagged in the catalog and prevents use of that copy without preventing access
to the others. Only legacy backups with a truly absent manifest retain
unverified download support.

Restore additionally requires `RESTORE_ENABLED=true` and is allowed only from
a modern, verified backup at the same revision. A maintenance gate drains
requests, an operating-system lock excludes concurrent backends and tools,
and a durable `.pfim-restore.json` journal makes crash recovery deterministic:
rollback before commit, roll-forward afterward. Each request uses an
idempotent `request_id` and the confirmed SHA-256. Its status remains available
through the `restore-operations` endpoint. The same protocol is available
offline with the backend stopped through `scripts/restore.ps1`; it does not
bypass live database validation or the mandatory pre-restore backup. See
[Setup](docs/setup.md#crash-safe-restore-opt-in),
[Data Safety](docs/data-safety.md#crash-safe-restore) and
[ADR 006](ADR/006-restore-sqlite-crash-safe.md).

## 🧪 Testing

```bash
# Run all tests: backend with coverage, then frontend
make test

# Run one side
make test-backend
make test-frontend

# Run a single file
cd backend
python -m pytest tests/unit/finance/test_portfolio.py -v
```

`backend/pytest.ini` already enables `--cov=app --cov-report=term-missing`.
Actual coverage is printed on every run; consult that output instead of a
fixed number here that would become outdated after subsequent commits.

**Targets**:

- Finance engine (`backend/app/finance/`): 100% coverage
- API: integration tests for critical flows using in-memory SQLite
- Frontend: Vitest covers domain and formatting utilities, lifecycle/import
  rules, backup state, capability-token HTTP client behavior, immutable CSV
  wizard sessions, multi-currency coupon previews, tax actions by origin,
  duplicate prices, FX diagnostics, coupon KPIs and scenario comparison by
  ID. Relevant components are checked through React static rendering with
  simulated data. Browser end-to-end tests are not yet available.

Integration tests build the schema using `Base.metadata.create_all`, which
is instantaneous but does not insert seed data. Since production schemas
are **always** built with Alembic,
`backend/tests/integration/test_migrations_match_models.py` follows the real
path: `alembic upgrade head` on an empty database, then compares the result
with `Base.metadata` table by table and column by column. Without it, adding
a model column but omitting the migration could pass the entire suite. The
startup guard provides a second defense: a mismatched database stops the
process before health checks and application queries.

### Test Sessions Must Match Production Sessions

`backend/tests/integration/conftest.py` builds its `sessionmaker` using exactly
the same parameters as `app.database.SessionLocal`. This matters because
`autoflush` determines whether a query sees rows the code has just queued.
With the default enabled, it sees them; in production, it does not.

That difference caused a real defect: CSV import recognized two identical
rows in the same file during tests but failed to recognize them in actual
use, losing the entire import while returning success (see
`backend/tests/integration/test_import_deduplication.py`). If a session
parameter changes on one side, update the other side too.

## 🔧 Development

### Create a New Migration

Generate and test migrations using a development or temporary database,
never `data/pfim.db`. Always check the resolved `DATABASE_URL` and follow
[Data Safety](docs/data-safety.md).

```bash
cd backend
alembic revision --autogenerate -m "Describe schema change"
alembic upgrade head
```

### Add a New Persistent Entity

1. Model: `backend/app/models/<entity>.py`, exported from
   `backend/app/models/__init__.py` so Alembic discovers it
2. Schema: `backend/app/schemas/<entity>.py`
3. Repository: `backend/app/repositories/<entity>_repo.py`
4. Service with invariants and orchestration:
   `backend/app/services/<entity>_service.py`
5. Router registered in the app: `backend/app/routers/<entity>.py`
6. Alembic migration tested first on a temporary database or authorized copy
7. Unit/integration tests for the contract, constraints, rollback and migration

When changing an existing entity, update only the layers actually affected,
while keeping the model, migration, contract and tests aligned.

### Code Style

```bash
make lint  # Format and check
```

Tools:

- `black` for Python formatting
- `isort` for import ordering
- `ruff` for static checks, such as unused imports and undefined names
- `eslint` for TypeScript

The three Python tools are configured in `backend/pyproject.toml`: line width
100 and the `black` profile for isort. Without that file, each tool used its
own defaults: black's 88 columns against roughly 100 in the code, and line
breaks different from isort's. `make lint` would therefore have rewritten the
entire repository in an unintended style.

These tools run on `app`, `tests` **and `migrations`**. Migrations are executed
Python code too, and excluding them allowed their style to drift.

## 📖 API Documentation

Swagger UI: http://localhost:8000/docs
ReDoc: http://localhost:8000/redoc

## 🛠️ Troubleshooting

### Database Locked

Do not delete, rename or overwrite the database. A lock generally means
another process is keeping a connection open:

1. Shut down all backend instances and windows opened by `start.bat` cleanly.
2. Check for any remaining `uvicorn`/Python processes.
3. Restart a single backend instance.
4. If the issue persists, retain the files and logs and follow the diagnosis
   procedure in [Data Safety](docs/data-safety.md).

Restore is not a solution to a lock. Do not enable or run it to bypass open
connections: first resolve the process holding the file. If recovery is
actually needed, use only the opt-in procedure documented in
[Data Safety](docs/data-safety.md), never manually copy over the live database.

Always build the schema with Alembic, never with `Base.metadata.create_all()`:
migrations also include technical defaults, such as tax settings, which
`create_all` does not insert. A new database contains no categories or CSV
profiles. See [ADR/005](ADR/005-alembic-from-first-commit.md).

### Port Already in Use

Windows symptom: uvicorn starts, prints `Will watch for changes…`, then:

```text
ERROR: [WinError 10013] An attempt was made to access a socket in a way
forbidden by its access permissions
```

Although the message mentions permissions, it usually means **the port is
already in use**, typically by a previous instance left running. Closing a
window with its X button does not always stop the process.

**Windows (PowerShell):**

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen | Select-Object OwningProcess
Stop-Process -Id <PID> -Force
```

**macOS / Linux:**

```bash
lsof -i :8000
kill -9 <PID>
```

Use the same procedure for the frontend on port `5173`.

If the port is free but the error persists, Windows may actually have
reserved it: Hyper-V, WSL and Docker reserve port ranges. Check with:

```powershell
netsh interface ipv4 show excludedportrange protocol=tcp
```

If `8000` falls in a listed range, start on another port
(`uvicorn app.main:app --port 8010`) and update `VITE_API_BASE_URL` in
`frontend/.env` accordingly.

### Python Dependencies

In the Windows x86-64 reference environment, reinstall from the hash lock:

```powershell
cd backend
python -m pip install --require-hashes -r pylock.toml
```

On macOS/Linux, the `Makefile` uses development declarations constrained by
`constraints-tested-win-py314.txt`; this does not provide the same
cross-platform guarantee as the Windows lock. For the frontend, always use
`npm ci` instead of `npm install` so the dependency tree comes from
`package-lock.json`.

## 📝 Development Phases (Roadmap)

The five phases produced the current application baseline. This does not
mean every historical specification requirement is implemented: the
specification records the normative status of requirements and the risk
register describes remaining work. Release details are in
[CHANGELOG.md](CHANGELOG.md).

- [x] Project setup
- [x] Finance engine and tests
- [x] Database schema and ORM
- [x] Pydantic schemas
- [x] Phase 1: Foundations (Transactions, Accounts, Categories)
- [x] Phase 2: Portfolio (FIFO, Prices)
- [x] Phase 3: Performance and Analysis (TWR, MWR, Dashboard)
- [x] Phase 4: Taxation and Advanced Reports
- [x] Phase 5: Forecasts and Refinements

## 📄 License

MIT

---

**For issues and questions**: Consult the technical specification in
`technical-specification.md`.
