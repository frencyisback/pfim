# Data Safety

PFIM manages real financial data. The operational file `data/pfim.db`, any
associated SQLite files and backups must not be deleted, renamed,
overwritten or used as test databases outside the explicit backup/restore
procedures described here and in ADR 006.

## Operational Boundaries

- The application is single-user and must bind only to `127.0.0.1`.
- The operational database is not a development or test environment.
- Tests, experimental migrations and audits must use in-memory SQLite, a
  temporary file or a separate, explicitly authorized copy.
- The default in the code and `backend/.env.example` is the isolated
  `data/pfim-dev.db` database; an `.env` file or process variable can override it.
- Before every Alembic command, check the effective `DATABASE_URL`. A process
  variable takes precedence over `backend/.env`; `backend/alembic.ini` does
  not determine the target.
- `alembic upgrade`, `downgrade` and `revision --autogenerate` are not
  diagnostic commands: they may read or modify the selected schema.
- The automatic startup check only reads the current Alembic heads. It does
  not migrate, stamp or create the schema. For file-based SQLite it uses
  `mode=ro` and rejects a nonexistent path without creating it.

A development database can use:

```dotenv
DATABASE_URL=sqlite:///../data/pfim-dev.db
```

The name must differ from `pfim.db` and every real backup.

## Local HTTP Protection

The backend accepts only configured loopback hosts and checks browser
`Origin` headers. Every `POST`, `PUT`, `PATCH` and `DELETE` additionally
requires `X-PFIM-Capability`, obtained from `GET /api/v1/security/capability`.
The random token lives only in process memory and changes at every restart;
do not save it in files or logs.

CORS also wraps the security and maintenance middleware: allowed origins
can read `CAPABILITY_REQUIRED`, `CAPABILITY_INVALID` and `MAINTENANCE_MODE`.
The frontend refreshes the token and retries once only for the two capability
rejections, which are issued before the handler. It does not automatically
retry a write with a lost response or a maintenance error. CORS preflight can
succeed during maintenance; the actual mutating request remains blocked by
the gate. Host checks remain active on actual requests. Unauthorized origins
remain rejected for mutations and capability bootstrap; for other reads,
CORS prevents browser access from an unauthorized origin.

These defenses reduce unintended or cross-origin mutating requests, but do
not provide multi-user authentication. Local reads do not require the
capability token: PFIM must not be exposed on a LAN or the Internet.

## Tests and Audits

The ordinary suite uses in-memory SQLite or temporary files. Before running
it in a new context, still set `DATABASE_URL=sqlite:///:memory:` in the test
process so a configuration error cannot reach the operational file. Also
set `BACKUP_ENABLED=false` and `RESTORE_ENABLED=false`. Dedicated fixtures
enable these features only on synthetic databases created in new temporary
directories. Backup regressions modify only test manifests and simulate
contention, slow copying and preliminary-backup timeouts; they neither
inspect nor repair real backups.

To analyze migration compatibility with real data:

1. Do not apply the migration to the operational database.
2. Obtain a consistent copy through the supported online backup or, only
   for a controlled external procedure, with the application stopped.
3. Work exclusively on the authorized copy.
4. Check `PRAGMA integrity_check`, the Alembic revision and domain invariants
   before and after the migration.
5. Keep the operational database unchanged until validation and explicit
   approval of the plan.

Do not infer or document the operational database's revision without an
authorized check on a separate copy.

If startup reports `Incompatible database schema`, do not bypass the guard
with manual changes or `alembic stamp head`: the latter only changes the
version marker and can make an incompatible schema appear compatible. A fix
requires a stopped backend, an explicitly verified target, a consistent
backup and a controlled Alembic migration.

### Checklist for an Authorized Operational Migration

Analysis on a copy and approval of the plan always precede work on the live
file. After authorization, an operational migration must follow this order:

1. Resolve and record the effective `DATABASE_URL`, current revision and
   code head; do not rely solely on the example value in `alembic.ini`.
2. Check integrity, foreign keys, absence of incomplete restores and the
   invariants or counts that must remain unchanged.
3. Use the PFIM service to create a verified online snapshot at the current
   revision and independently check its database, manifest, SHA-256,
   revision, integrity and absence of sidecars.
4. Stop the backend and verify the PFIM instance lock before touching the
   schema. Merely not seeing a window or process name does not prove quiescence.
5. Apply the exact approved revision, rather than a generic `head` if other
   migrations may have appeared in the meantime.
6. Only after a successful upgrade, align `EXPECTED_ALEMBIC_REVISION` with
   the distributed revision.
7. Compare preexisting data between snapshot and live database, then repeat
   integrity and FK checks, schema validation, current/head checks and the
   schema guard.
8. Create and verify a new backup at the updated revision, then run startup,
   the health check and `GET /api/v1/backup/status`.
9. Retain the operation record and copy both database and manifest of at
   least one verified backup to a physically separate drive.

`make migrate` and the convenience scripts do not replace this checklist
for the operational database: explicitly verify the target, quiescence and
exact authorized revision. Do not force an earlier-revision backup into a
new build's restore through `stamp`; rollback requires a coordinated plan
for code, schema and configuration. Before a downgrade, also preserve all
data in columns that the migration removes.

## Database Locked

Do not delete the file to resolve a lock.

1. Shut down the frontend and backend cleanly.
2. Check for other Python/uvicorn instances using PFIM.
3. Check for backups, antivirus software or synchronization processes
   keeping files open.
4. Retain the database, any `-wal`/`-shm` files and logs. Do not remove or copy
   them separately without a consistent SQLite procedure.
5. Restart one instance. If the lock persists, diagnose using a copy and do
   not attempt destructive commands.

Restore does not resolve a lock. Do not enable it to force replacement of a
file still in use by external processes.

## Supported Online Backup

Backup creation is disabled by default. The deployment must explicitly set
`BACKUP_ENABLED=true` and
`EXPECTED_ALEMBIC_REVISION=<exact build revision>`. The effective status is
exposed by `GET /api/v1/backup/status`.

The service used by the interface, API, `make backup` and
`scripts/backup.ps1`:

1. Opens the source database read-only.
2. Uses the SQLite Online Backup API to obtain a consistent snapshot even
   while the application is active.
3. Writes to a unique name with a `.partial` suffix.
4. Checks SQLite integrity, foreign keys and the expected Alembic revision.
5. Calculates SHA-256 and creates a manifest synchronized to disk.
6. Publishes the manifest and database through atomic renames only after
   validation.

`BACKUP_COPY_TIMEOUT_SECONDS` limits the online copy loop: the default is
60 seconds, with integer values from 1 to 600 allowed. The deadline uses a
monotonic clock and is checked in the progress callback, including during
SQLite `BUSY`/`LOCKED` retries. Each SQLite attempt waits at most 100 ms and
never exceeds `SQLITE_BUSY_TIMEOUT_MS`. The limit is not a hard guarantee
for operating-system I/O, validation, `fsync` or the complete procedure.

On expiry, the service interrupts the copy, closes connections and returns
`503 BACKUP_TIMEOUT`. The CLI reports the same code and exits with an error.
The error path removes only staging artifacts generated by that invocation
and does not publish an incomplete backup. No automatic retry starts.

A modern backup is therefore an inseparable pair:

- `pfim_backup_....db`;
- `pfim_backup_....manifest.json`.

Download and retain both. Validation shared by the catalog, download,
manifest and restore selection requires a JSON object with a supported
version, matching name, positive integer size, valid SHA-256, nonempty
revision, successful checks and a timezone-aware ISO timestamp. Version,
size and violation count do not accept booleans in place of integers. The
date is normalized to UTC only in memory; no manifest is rewritten. Hash,
link, sidecar and file-stability checks remain active.

A missing, invalid or unsupported manifest makes that individual item
unverified. It remains visible with a fallback filesystem date and does not
prevent access to other backups. The API `verification_error` field
distinguishes `manifest_missing`, `manifest_invalid`, `hash_mismatch`,
`sidecars_present` and `backup_changed`. The interface displays the reason
and aligns available actions with server checks.

Download remains allowed for a legacy backup only when the manifest is truly
absent and other file checks pass. A present but invalid manifest, including
a directory or dangling link, blocks download even for a legacy filename.
A modern backup without a manifest is likewise blocked. All unverified
backups remain excluded from restore.

A copy in the same directory or on the same drive does not protect against
hardware failure, theft or storage corruption. Keep at least one copy of
the database/manifest pair on separate, protected storage.

## Crash-Safe Restore

Restore is a high-impact maintenance feature and remains disabled by default.
Intentionally enabling it requires all of:

```dotenv
BACKUP_ENABLED=true
RESTORE_ENABLED=true
EXPECTED_ALEMBIC_REVISION=<exact build revision>
```

The effective status is exposed by `GET /api/v1/backup/status`. During restore,
it includes maintenance mode, runtime state and the active identifier. The
flag does not make a legacy, modified or different-revision backup eligible.

### Mandatory Preconditions

Before confirming:

1. Check the effective `DATABASE_URL` and explicitly approve that target.
2. Select only a modern `.db` + `.manifest.json` pair marked
   `restore_eligible` by the catalog.
3. Compare the manifest filename, SHA-256 and revision with those shown by
   the application and with the build's expected revision.
4. Already retain a copy of the pair on separate, protected storage.
5. Use a UUID `request_id` and confirm exactly `RESTORE {filename}`.

The service rechecks the filename, SQLite header, hash, integrity, foreign
keys and revision before and after staging. The candidate is copied into a
separate file on the same filesystem and validated again; the original
backup and manifest are never used as a work area. Before the swap, a new
verified online backup of the current database is also created.

The preliminary backup uses the same `BACKUP_COPY_TIMEOUT_SECONDS`. On expiry,
restore fails with `BACKUP_TIMEOUT` before any swap: the current database
stays in place, copy staging is cleaned up, and the gate and locks are
released. The operation record retains its `failed` status and error code.
Resubmitting the same `request_id` returns a 409 conflict with the recorded
status and does not start a second copy; status remains available through
the operation endpoint.

### Quiescence, Locks and SQLite Sidecars

The backend holds an instance lock throughout its lifetime. HTTP restore
activates a maintenance gate, blocks new requests and waits for already
admitted requests to finish. Backup, restore and recovery also share an
interprocess operation lock. The offline CLI acquires the instance lock
with zero timeout and therefore refuses to operate while the backend is
still active.

After draining, the service closes the engine, performs a WAL checkpoint,
validates the live database and removes `-wal`/`-shm` sidecars only when no
external connection keeps them open. A remaining rollback journal, busy
checkpoint or antivirus/synchronization handle causes the operation to fail
before commit; none of these permits forced deletion.

### Journal and Crash Recovery

The durable `data/.pfim-restore.json` journal records three phases:

- `prepared`: staging and the pre-restore backup are ready;
- `live_moved`: the previous database is in the rollback area, but commit
  has not occurred;
- `committed`: the candidate is installed, verified and reopened.

Before `committed`, recovery restores the previous database. After
`committed`, it keeps the candidate and completes cleanup. Recovery starts
under the lock before the startup schema guard; a second execution is
idempotent. Each request additionally has a durable
`.pfim-restore-operation-{request_id}.json` record, available through
`GET /api/v1/backup/restore-operations/{request_id}`.

Do not manually delete, modify or rename the journal, operation records or
`.candidate.db`/`.rollback.db` files. If a hash differs or the files do not
allow a deterministic choice, PFIM remains fail-closed with
`RESTORE_RECOVERY_REQUIRED`. Retain the entire directory and logs and
diagnose using a copy; do not try to "complete" the swap manually.

### Offline Maintenance

To restore with the backend stopped, close every instance and run from the
project root:

```powershell
.\scripts\restore.ps1 `
  -Filename "pfim_backup_....db" `
  -ExpectedSha256 "<sha256 from the manifest>"
```

The script requests the exact confirmation and optionally accepts
`-RequestId` for an identifiable retry. It recovers a pending journal before
the schema guard, but a new operation still requires a verifiable live
database for the pre-restore backup. It does not offer a shortcut to overwrite
an already corrupted file or one at an incompatible revision. It does not
run `alembic upgrade`, `stamp` or `create_all`. The complete procedure and
examples are in [Setup](setup.md#crash-safe-restore-opt-in); commit points
are normative in [ADR 006](../ADR/006-restore-sqlite-crash-safe.md).
