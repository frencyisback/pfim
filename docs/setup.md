# Development Environment Setup

## Reference Runtimes

PFIM uses explicit versions rather than generic ranges:

- Python 3.14.6 (`.python-version`);
- Node.js 26.4.0 (`.node-version`);
- npm 11.17.0 (`frontend/package.json`).

Before setup, check:

```text
python --version
node --version
npm --version
```

`backend/pylock.toml` contains versions and hashes for Windows x86-64 with
Python 3.14. `frontend/package-lock.json` is applied through `npm ci`.
The `requirements*.txt` files declare dependencies; they are not the primary
reproducible installation path for Windows.

Before any migration, read [Data Safety](data-safety.md). The default is
`data/pfim-dev.db`, but an environment variable or custom `.env` can point
scripts elsewhere: always check the effective `DATABASE_URL`.

## Windows (Reference Environment, Without `make`)

From the project root:

```powershell
# Complete setup: venv + hash-verified pylock + npm ci
.\scripts\setup.ps1

# Alembic migrations, only after checking DATABASE_URL
.\scripts\migrate.ps1

# Development, in two separate terminals
.\scripts\dev-backend.ps1
.\scripts\dev-frontend.ps1

# Tests
.\scripts\test-backend.ps1
.\scripts\test-frontend.ps1

# Lint
.\scripts\lint.ps1

# Verified online backup; no need to stop the application
.\scripts\backup.ps1

# Crash-safe offline restore; requires a stopped backend, opt-in and manifest hash
.\scripts\restore.ps1 -Filename <backup.db> -ExpectedSha256 <sha256>
```

`setup.ps1` creates `backend/venv`, installs `backend/pylock.toml` using
`--require-hashes`, runs `npm ci` and copies both `.env.example` files only
when their corresponding `.env` files do not exist. It requires a pip version
that can install `pylock.toml`; if pip reports that the format is unsupported,
upgrade it within the virtual environment and rerun the script.

If `venv\Scripts\Activate.ps1` is blocked, prefer a process-scoped policy
(`Set-ExecutionPolicy -Scope Process Bypass`) after reviewing the scripts.
Permanently changing the user's policy or installing a trusted certificate
widens the scope of trust.

### Signing PowerShell Scripts

Changing a `.ps1` file invalidates its Authenticode signature. After code
review, scripts can be signed with:

```powershell
.\scripts\setup-code-signing.ps1   # One-time setup of a local certificate
.\scripts\sign-all.ps1             # Repeat after each script change
```

Alternatively, for files from a verified archive:

```powershell
Get-ChildItem -Path .\scripts\*.ps1 -Recurse | Unblock-File
```

## macOS/Linux

The `Makefile` uses the same required runtimes, `npm ci` and Python versions
constrained by `constraints-tested-win-py314.txt`:

```bash
make install
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env

# Check backend/.env before this command
make migrate

# Start in two separate terminals
make dev-backend
make dev-frontend
```

The Python hash lock is limited to Windows x86-64. The POSIX path uses
`requirements-dev.txt` with the constraints file, so it does not guarantee
identical dependency artifacts on every platform.

## Database and Migrations

The `backend/.env.example` template uses:

```dotenv
DATABASE_URL=sqlite:///../data/pfim-dev.db
```

`alembic upgrade head` applies the entire migration chain to the target and
inserts technical defaults, including tax settings. A new database contains
no categories or CSV import profiles; users create their own. System
categories are created automatically when relevant operations first need
them. Alembic is the supported way to create the schema:
`Base.metadata.create_all()` applies neither migrations nor seed data.

Alembic obtains the database from `backend/app/config.py`: process variables
and `backend/.env` are the actual sources; the example URL in
`backend/alembic.ini` does not determine the target. An environment variable
takes precedence over the `.env` file.

### How `DATABASE_URL` Is Interpreted

A relative path is resolved against `backend/`, not the directory from which
the command runs. For example, `sqlite:///../data/pfim-dev.db` always points
to the same development file. An absolute path stays at its declared location.

However, not everything after `sqlite:///` represents a file:

| Value | Meaning |
|---|---|
| `sqlite:///:memory:` or `sqlite://` | In-memory database, lost when closed |
| `sqlite:///file:...?uri=true` | SQLite URI with its options |
| `postgresql://...` | Another engine; no path resolution |

The behavior is covered by `backend/tests/unit/test_database_url.py`.

### Startup Schema Check

Before accepting requests, the FastAPI lifespan compares the heads in the
`backend/migrations` chain with the current heads recorded in
`alembic_version`. They must match exactly: merely having some expected
columns is insufficient.

If the database is missing, has no revision, is behind or ahead, or is on a
different branch, Uvicorn stops startup and the message reports
`expected=<code head>` and `found=<database head>`. Even the health check is
unavailable in this state: `Application startup complete` therefore means
the check has succeeded.

The check is diagnostic only:

- It does not run `alembic upgrade`, `stamp` or `revision`.
- It does not use `Base.metadata.create_all()`.
- It does not create a missing SQLite file.
- It opens file-based SQLite databases through a separate `mode=ro` connection.

To fix a mismatch, stop the backend, verify the effective `DATABASE_URL`,
create a consistent validated backup, then follow the controlled Alembic
procedure. Do not add columns manually or use `alembic stamp head` to hide
an unmigrated schema.

## Backend and Local HTTP Protection

The backend must bind to `127.0.0.1:8000`. Check:

- Health check: http://localhost:8000/api/v1/health;
- Swagger UI: http://localhost:8000/docs.

The frontend automatically obtains a volatile token from
`GET /api/v1/security/capability` and sends it in the `X-PFIM-Capability`
header for every `POST`, `PUT`, `PATCH` and `DELETE`. A direct API client must
do the same; in Swagger, request the token first and enter it through
**Authorize**. The token lives only in memory, changes on every restart and
must not be stored in configuration files or logs.

After a restart, the frontend can read the `403 CAPABILITY_INVALID` response,
refresh the token and retry the request once. CORS also covers protection
and maintenance errors for allowed origins. Network errors and maintenance
503 responses do not automatically retry writes; preflight does not bypass
the block on the actual request.

Checks on `Host`, `Origin` and the capability token limit local HTTP abuse,
but do not provide multi-user authentication. Do not expose PFIM on a LAN or
the Internet.

## Frontend

The supported installation uses the lock file:

```bash
cd frontend
npm ci
cp .env.example .env
npm run dev
```

Check that http://localhost:5173 displays the application.

## Verified Online Backup

Backup and restore are fail-closed by default. To enable backup creation,
configure these settings intentionally:

```dotenv
BACKUP_ENABLED=true
EXPECTED_ALEMBIC_REVISION=<exact revision shipped with the build>
# Copy-loop limit: integer from 1 to 600 seconds; default 60
BACKUP_COPY_TIMEOUT_SECONDS=60
```

Do not copy a value found in a database into this document: the expected
revision belongs to the build and must be set in its environment. Read the
effective status through `GET /api/v1/backup/status`.

`make backup`, `scripts/backup.ps1` and `POST /api/v1/backup` use the same
service. The snapshot is taken through the SQLite Online Backup API even
while the application is active. It starts as a `.partial` file and is
published only after:

- `PRAGMA integrity_check`;
- Foreign-key validation;
- Comparison with the expected Alembic revision;
- SHA-256 calculation;
- Manifest writing and synchronization.

The copy deadline uses a monotonic clock and is checked in the progress
callback, including SQLite `BUSY`/`LOCKED` retries. Each SQLite attempt waits
at most 100 ms and never exceeds `SQLITE_BUSY_TIMEOUT_MS`. On expiry, the API
returns `503 BACKUP_TIMEOUT` and the CLI prints `BACKUP_TIMEOUT` and exits
with code 1. Connections close, the invocation's staging files are cleaned
up, and no incomplete backup is published. There is no automatic retry. The
limit covers the copy loop; it does not impose a hard deadline on operating
system I/O, validation, `fsync` or the complete backup/restore procedure.

Always retain and transfer the backup file together with its
`*.manifest.json`. The interface and `/download` and `/manifest` endpoints
allow separate downloads. A copy on the same storage device is not a complete
strategy: keep at least one copy off that drive as well.

The catalog, download and restore share manifest validation: JSON object,
supported version, name, positive integer size, SHA-256, nonempty revision,
successful checks and a timezone-aware ISO timestamp. Booleans are not valid
as versions, sizes or violation counts. Timestamp normalization to UTC occurs
only in memory. Hash, link, sidecar and file-stability checks remain in place;
existing manifests are neither repaired nor rewritten.

An unverified file remains in the catalog with an API `verification_error`
reason and a fallback filesystem date if its manifest is unusable. Reasons
are `manifest_missing`, `manifest_invalid`, `hash_mismatch`,
`sidecars_present` and `backup_changed`. The UI displays these without
blocking access to healthy backups. Legacy download is allowed only when
the manifest is truly absent and all other checks pass. A present but invalid
manifest, including a directory or dangling link, blocks download. Modern
download always requires a valid manifest.

## Crash-Safe Restore (Opt-In)

Restore remains disabled by default. It is available only when all three
settings are intentionally configured and consistent:

```dotenv
BACKUP_ENABLED=true
RESTORE_ENABLED=true
EXPECTED_ALEMBIC_REVISION=<exact revision shipped with the build>
# Allowed range: 1–300 seconds; default 30
RESTORE_QUIESCE_TIMEOUT_SECONDS=30
# Pre-restore backup copy-loop limit: 1–600 seconds; default 60
BACKUP_COPY_TIMEOUT_SECONDS=60
```

`RESTORE_ENABLED=true` alone is insufficient: restore must be able to create
the verified pre-operation backup, and the candidate must match the build
revision. Do not derive `EXPECTED_ALEMBIC_REVISION` from the candidate or the
database being replaced, and do not use restore as a migration shortcut.
`RESTORE_QUIESCE_TIMEOUT_SECONDS` limits the wait for already admitted
requests; on expiry, the operation is canceled before the swap.

If the preliminary backup's copy loop expires instead, restore ends with
`503 BACKUP_TIMEOUT` before the swap. Copy staging is removed, the gate and
locks are released, and the operation record remains `failed` with the error
code. The current database is not replaced.

An item returned by `GET /api/v1/backup` can be restored only if
`restore_eligible` is `true`. Legacy backups without manifests, modified files
and different revisions remain ineligible; `restore_ineligible_reason`
explains why. Before confirming, note the filename and SHA-256 displayed by
the catalog/manifest.

### Restore Through the Local API

The mutating request requires the standard `X-PFIM-Capability` header and an
explicit body:

```json
{
  "request_id": "00000000-0000-4000-8000-000000000001",
  "expected_sha256": "<64 lowercase hexadecimal characters>",
  "confirmation": "RESTORE pfim_backup_....db"
}
```

Send it to `POST /api/v1/backup/{filename}/restore`. `request_id` is the
idempotency key: a retry with the same filename and hash returns the result
of an already completed operation. For an attempt ending in `failed` or
`rolled_back`, the same ID returns 409 with the recorded state and does not
start another copy. Reusing the ID with different parameters is also a
conflict. Durable status is available through
`GET /api/v1/backup/restore-operations/{request_id}`. During quiescence, new
ordinary requests receive `503 MAINTENANCE_MODE` and `Retry-After`; health,
backup status and operation status remain available.

### Offline Restore on Windows

Use the CLI for entirely offline maintenance when the live database can
still be verified:

1. Close the frontend, backend and every other Python/Uvicorn instance.
2. Check the effective `DATABASE_URL` and ensure the backup and its manifest
   are in the configured database directory.
3. From the project root, run:

   ```powershell
   .\scripts\restore.ps1 `
     -Filename "pfim_backup_....db" `
     -ExpectedSha256 "<sha256 from the manifest>"
   ```

4. Type the exact confirmation proposed by the script. To retry an operation
   with a previously chosen identifier, add `-RequestId "<UUID>"`.
5. Retain the JSON output with `operation_id` and status, then restart a
   single backend instance.

The CLI acquires the instance lock with a zero timeout. If Uvicorn is still
active, it fails without starting restore. The API and CLI use the same
operation lock, pre-restore backup and journal. The CLI recovers a pending
journal before the schema guard, but a new restore still runs the guard and
must be able to verify and back up the live database. This is not a path to
automatically overwrite an already corrupted database or one with an
incompatible revision.

### Commit and Recovery

The candidate is copied into staging on the database's filesystem. The
durable `.pfim-restore.json` journal moves through `prepared`, `live_moved`
and `committed`. A crash before `committed` rolls back to the previous
database; after `committed`, recovery keeps the candidate and completes
cleanup. Recovery runs under the lock before the startup Alembic check.

Do not delete or rename `.pfim-restore.json`,
`.pfim-restore-*.candidate.db`, `.pfim-restore-*.rollback.db` or
`.pfim-restore-operation-*.json` records. If hashes, the journal or the
rollback file do not permit a deterministic decision, the backend remains
fail-closed with `RESTORE_RECOVERY_REQUIRED`. Retain all files and diagnose
using a copy. The complete protocol and commit points are defined in
[ADR 006](../ADR/006-restore-sqlite-crash-safe.md).

## Tests

```bash
# Everything
make test

# Separately
make test-backend
make test-frontend
```

On Windows, use the equivalent scripts shown above. `backend/pytest.ini`
already enables coverage (`--cov=app --cov-report=term-missing`). Most
integration tests use in-memory SQLite; migration, concurrency, backup,
restore and fault-injection tests use isolated temporary files.

In the verification process, set `DATABASE_URL=sqlite:///:memory:`,
`BACKUP_ENABLED=false` and `RESTORE_ENABLED=false`. Backup/restore fixtures
explicitly override configuration and paths only for synthetic databases in
new temporary directories. Backup regressions cover mixed catalogs with
malformed manifests, persistent/transient contention, slow progress and
pre-restore failure before the swap, including 409 replay of the same request
ID without a second copy. They do not use operational databases or backups.

On the frontend, `npm test` runs Vitest on domain utilities, formatters,
import/lifecycle rules, backup state and the capability-token HTTP client,
as well as controllers with simulated asynchronous responses and static
React component rendering. These checks do not constitute an end-to-end
browser suite.
