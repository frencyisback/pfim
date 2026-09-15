# ADR 004: pip with a verified lock instead of Poetry

**Status:** Accepted (updated decision)  
**Last reviewed:** 2026-08-28

## Context

The first specification version called for Poetry, while the project was
implemented with pip and `requirements*.txt` files. Version ranges in these
files describe direct dependencies but do not make the environment
reproducible: two installations may resolve different transitive versions
or artifacts.

PFIM is a local single-user application and does not need Poetry's package
publishing features. It does need a reproducible environment for running
financial code, migrations, and tests, with verified installation artifacts.

## Decision

pip remains the sole Python dependency manager; Poetry is not introduced.
Dependency declarations and reproducibility have separate roles:

- `backend/requirements.txt` and `backend/requirements-dev.txt` declare direct
  dependencies and compatible version ranges;
- `.python-version` pins Python 3.14.6 for the reference environment;
- `backend/constraints-tested-win-py314.txt` records versions, including
  transitive dependencies, validated on Windows x86-64 with Python 3.14.6;
- `backend/pylock.toml` pins versions, wheels, and hashes for that environment;
  `scripts/setup.ps1` installs it with
  `pip install --require-hashes -r pylock.toml`;
- on macOS/Linux, the `Makefile` uses the declarations with the constraints
  file: this is a constrained development path, but it is not equivalent to
  a platform-specific artifact lock with hashes;
- the frontend uses `frontend/package-lock.json` through `npm ci`.
  `.node-version` and the `packageManager`/`engines` fields in
  `frontend/package.json` pin Node.js 26.4.0 and npm 11.17.0.

## Rationale

- Retaining pip avoids a second manager and keeps local setup simple.
- The Python lock with hashes makes the Windows environment used for the
  full suite verifiable and repeatable.
- Separating declarations, validated versions, and the lock avoids implying
  that `requirements*.txt` ranges provide guarantees they cannot offer.
- `npm ci` applies the frontend lock without implicitly updating it.

## Consequences

- Supported Windows setup must install from `pylock.toml` rather than
  resolving the `requirements*.txt` ranges again.
- A Python upgrade requires deliberate updates to declarations if needed,
  validated versions, and the lock with hashes, followed by the full suite
  and relevant migration/backup checks.
- Frontend upgrades must update and version `package.json` together with
  `package-lock.json`, validated using `npm ci`, tests, lint, and build.
- The current Python lock explicitly targets Windows AMD64 / Python 3.14
  only. It must not be used to claim equivalent reproducibility on macOS
  or Linux.
- Bringing a POSIX platform to the same level requires a lock with hashes
  for the supported combination and a CI suite run from that lock; without
  this evidence, support remains best-effort.
