# ADR 006: Crash-safe SQLite restore with maintenance and a durable journal

**Status:** Accepted  
**Last contract verification against code:** 2026-09-10

## Context

PFIM uses a local SQLite database. Replacing the operational file while
connections, requests, or writes are still active can produce a partial
database or one inconsistent with its `-wal`/`-shm` sidecars. The former
restore implementation that copied the file directly was removed because
`engine.dispose()` alone does not quiesce sessions already handed out, and
a progressive copy has no atomic commit point.

Recovery must also work when a crash interrupts the process between moving
the previous database and publishing the candidate. Recovery of a pending
journal must precede the schema guard; a new offline operation is possible
only if the live database can still be verified, because a pre-restore
backup is mandatory.

## Decision

Restore remains disabled by default. It is available only when
`RESTORE_ENABLED=true`, `BACKUP_ENABLED=true`, and
`EXPECTED_ALEMBIC_REVISION` identifies exactly the single head shipped with
the build. No fallback migrates, stamps, or accepts different revisions
during restore.

The API and offline CLI delegate to the same protocol:

- `POST /api/v1/backup/{filename}/restore` accepts a UUID `request_id`, the
  SHA-256 already shown to the user, and the exact confirmation
  `RESTORE {filename}`;
- `GET /api/v1/backup/restore-operations/{request_id}` exposes the operation's
  durable state. Retrying the POST with the same parameters returns its
  result if already completed; a `failed` or `rolled_back` attempt returns
  409 with the recorded state and does not start another operation;
- `scripts/restore.ps1` uses the same service with the backend stopped and
  refuses to start if Uvicorn holds the instance lock.

### Quiescence and exclusion

The backend holds an operating-system instance lock for its entire
lifetime. A second backend and the offline CLI cannot operate on the same
`data/` directory. Backup, restore, and recovery also share an interprocess
operation lock.

For HTTP restore, a maintenance gate prevents new requests from entering,
waits for admitted requests to finish, and returns `503` with `Retry-After`
during maintenance. Only the control endpoints required for health, backup
status, and operation status remain readable. A drain timeout cancels the
restore before changing the operational file.

### Candidate and safety backup

The candidate must be a modern backup with a valid filename and consistent
manifest. At least the following are verified before any swap:

- JSON manifest structure, supported version, and field types, without
  accepting booleans as version, size, or violation count;
- positive size, nonempty revision, successful checks, and an ISO timestamp
  with a time zone; any UTC normalization remains in memory only;
- SQLite header, `PRAGMA integrity_check`, and foreign keys;
- manifest name, size, and SHA-256, including the SHA-256 confirmed by the caller;
- Alembic revision exactly matching the one expected by the build;
- candidate immutability while copying to staging on the same filesystem
  as the operational database.

A new verified online backup of the current database is always created
before the swap. The original candidate and its manifest are never renamed,
overwritten, or used as working space.

The catalog, download, manifest, and restore selection share the same
validation. A file with an invalid manifest remains visible as unverified,
with a fallback filesystem date and `verification_error`, without
invalidating other catalog entries. Legacy download is allowed only when
the manifest is genuinely absent, subject to the other checks; a present
but invalid manifest also blocks legacy download. No unverified file
becomes eligible for restore.

The backup copy loop, including the pre-restore backup, uses
`BACKUP_COPY_TIMEOUT_SECONDS`: default 60 seconds, an integer in the range
1–600. A monotonic deadline is checked in the progress callback and during
`BUSY`/`LOCKED` retries; the SQLite wait per attempt is limited to the
smaller of 100 ms and `SQLITE_BUSY_TIMEOUT_MS`. Expiration produces
`503 BACKUP_TIMEOUT`, closes connections, and removes that invocation's
staging files without publishing an incomplete copy. During pre-restore,
the error precedes any swap: gate and locks are released, the operation
record retains `failed` and the original code, and the same request ID
produces 409 without another copy. This limit does not guarantee a hard
maximum for operating-system I/O, validation, `fsync`, or the whole restore.

### Commit point and recovery

Staging, rollback, and the journal live beside the operational database, so
replacements remain on the same filesystem. The durable journal
`data/.pfim-restore.json` uses three phases:

1. `prepared`: the candidate is staged and the pre-restore backup published,
   but the previous database is still authoritative;
2. `live_moved`: the previous database has been moved to the rollback area;
   until the next phase is published, every crash causes rollback to the
   previous database;
3. `committed`: the candidate is installed, validated, and reopened at the
   expected revision; from this commit point, recovery rolls forward and
   completes cleanup only.

Every transition and operation record is written using a temporary file,
flush, `fsync`, and durable replacement. On Windows, replacement uses a
rename primitive with replace and write-through; a progressive copy is
never performed over `pfim.db`.

Journal recovery runs under lock **before** the startup schema guard.
Before `committed`, it restores the previous database; after `committed`,
it retains the candidate and completes cleanup. Rollback is also restartable
if a second crash occurs during recovery. If an already committed candidate
is missing or altered, no implicit rollback occurs: startup fails closed
and preserves the candidate, rollback, and journal for diagnosis. More
generally, if the journal, operation record, rollback, or hashes do not
permit a deterministic decision, startup fails closed with
`RESTORE_RECOVERY_REQUIRED`: files are not deleted heuristically.

## Consequences

- Restore is a maintenance procedure, not an ordinary CRUD mutation.
- A legacy backup genuinely lacking a manifest remains downloadable
  subject to the other catalog checks, but is not eligible for restore.
  A verified pair at a different revision remains downloadable, but cannot
  be restored with the current build. A present, invalid manifest blocks download.
- The offline CLI permits controlled maintenance with the backend stopped
  and recovers any pending journal before the guard. It bypasses neither
  live database validation nor the mandatory pre-restore backup; explicit
  opt-in configuration, a hash, and confirmation are still required.
- Antivirus software, synchronization, or external processes holding SQLite
  handles can cause quiescence or rename to fail. The protocol fails before
  commit or preserves the journal for recovery, without forcing file loss.
- The reference reproducible environment remains Windows AMD64/Python 3.14.
  The POSIX path remains best-effort until it has equivalent locks,
  artifacts, and CI.
- Fault injection and real process termination must cover every journal
  boundary; tests must use isolated temporary databases only. A19/A20
  regressions use fresh synthetic manifests and databases, a controlled
  clock, persistent/transient contention, and preliminary backup failure,
  checking cleanup, lock release, and failure idempotency.

## Rejected alternatives

- Copying the backup directly over the live file.
- Treating `engine.dispose()` as sufficient for quiescence.
- Performing restore and Alembic migration in the same operation.
- Allowing restore from legacy backups or without a confirmed hash.
- Deleting journals, sidecars, or rollback files when recovery is not deterministic.
