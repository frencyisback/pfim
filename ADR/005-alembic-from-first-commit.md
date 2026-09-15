# ADR 005: Alembic configured from the first commit

**Status:** Accepted  
**Last reviewed:** 2026-08-17

## Context
The data schema will evolve substantially in the initial development stages
(Phases 1–2).

## Decision
Configure Alembic immediately, instead of starting with
`Base.metadata.create_all()` and adding migrations only once the schema stabilizes.

## Rationale
- Every schema change, including early changes, remains versioned and reproducible.
- Avoids a difficult transition that would require reconstructing migration
  history retrospectively.
- Establishes schema versioning as an explicit project requirement.

## Consequences
- Every ORM model change requires a migration (`alembic revision
  --autogenerate`) instead of a simple `create_all()`.
- The actual chain in `backend/migrations/` is part of the product and is
  verified against temporary databases by integration tests.
- Generating and applying a migration must explicitly target a development
  database or copy: Alembic does not make it safe to change the operational
  database without a backup and validation.
