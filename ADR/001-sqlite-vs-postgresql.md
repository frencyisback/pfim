# ADR 001: SQLite database with SQLAlchemy abstraction

**Status:** Accepted  
**Last reviewed:** 2026-08-29

## Context
PFIM is a local, single-user desktop application (see specification §1.3:
multi-user access and cloud synchronization are outside the scope of v1.0).

## Decision
Use SQLite as the database, with all data access mediated by SQLAlchemy 2.0
(Repository Pattern; see specification §3.2, §12.1).

## Rationale
- Zero configuration, a single file (`data/pfim.db`), suitable for single-user use
- No external service to install or manage
- SQLAlchemy reduces dialect dependence and keeps the persistence boundary explicit

## Consequences
- Some advanced PostgreSQL features (high write concurrency and advanced
  types) are unavailable. Even in single-user use, the browser can send
  concurrent requests: PFIM serializes writers with explicit transactions
  and exposes contention rather than assuming it does not exist.
- The current code includes SQLite-specific choices: PRAGMAs, `BEGIN
  IMMEDIATE`, the SQLite Online Backup API, batch migrations, and dedicated
  file-based tests. Application restore is disabled by default and, when
  deliberately enabled, follows the crash-safe maintenance protocol defined
  in [ADR 006](006-restore-sqlite-crash-safe.md); it is not an ordinary file copy.
- A possible move to PostgreSQL therefore requires reviewing persistence,
  migrations, concurrency, backup/recovery, operations, and tests; changing
  the connection string alone is insufficient.
