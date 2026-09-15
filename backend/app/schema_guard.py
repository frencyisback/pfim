"""Fail fast when the database Alembic revision differs from the code. This startup check only
reads revisions; it never applies, generates, or stamps migrations.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import urlencode

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Engine

BACKEND_DIR = Path(__file__).resolve().parent.parent


class SchemaCompatibilityError(RuntimeError):
    """The configured database cannot be used by the current build."""


def code_alembic_heads() -> tuple[str, ...]:
    """Return heads declared by the bundled Alembic chain. ScriptDirectory only reads migration
    files; it neither loads migrations/env.py nor opens the configured database.
    """

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    heads = tuple(sorted(ScriptDirectory.from_config(config).get_heads()))
    if not heads:
        raise SchemaCompatibilityError(
            "Cannot verify schema compatibility: the code declares no Alembic head"
        )
    return heads


def _is_sqlite_memory(engine: Engine) -> bool:
    database = engine.url.database
    if database in {None, "", ":memory:"}:
        return True
    return str(database).startswith("file:") and engine.url.query.get("mode") == "memory"


def _sqlite_read_only_uri(engine: Engine) -> str:
    """Build a SQLite mode=ro connection that cannot create files. Preserve options on explicit
    SQLite URIs while forcing read-only mode; ordinary file URLs from app.database are already
    absolute.
    """

    database = str(engine.url.database)
    if database.startswith("file:"):
        query = {
            key: value for key, value in engine.url.query.items() if key not in {"uri", "mode"}
        }
        query["mode"] = "ro"
        return f"{database}?{urlencode(query)}"

    database_path = Path(database)
    if not database_path.is_file():
        raise FileNotFoundError(database_path)
    return f"{database_path.resolve().as_uri()}?mode=ro"


def _sqlite_current_heads(engine: Engine) -> tuple[str, ...]:
    """Read alembic_version without the application's writable engine."""

    try:
        uri = _sqlite_read_only_uri(engine)
        with sqlite3.connect(uri, uri=True, timeout=0) as connection:
            connection.execute("PRAGMA query_only = ON")
            version_table_exists = connection.execute(
                "SELECT 1 FROM sqlite_master " "WHERE type = 'table' AND name = 'alembic_version'"
            ).fetchone()
            if version_table_exists is None:
                return ()
            rows = connection.execute(
                "SELECT version_num FROM alembic_version ORDER BY version_num"
            ).fetchall()
    except FileNotFoundError:
        raise
    except sqlite3.Error as exc:
        raise SchemaCompatibilityError(
            f"Cannot read the Alembic revision in read-only mode: {exc}"
        ) from exc

    return tuple(sorted(str(row[0]) for row in rows))


def database_alembic_heads(engine: Engine) -> tuple[str, ...]:
    """Read current database heads without changing the schema. File-based SQLite uses a separate
    mode=ro connection so a wrong path cannot silently create an empty database. In-memory
    SQLite must use its owning engine, which also allows file-free guard tests.
    """

    if engine.url.get_backend_name() == "sqlite" and not _is_sqlite_memory(engine):
        return _sqlite_current_heads(engine)

    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        return tuple(sorted(context.get_current_heads()))


def _describe_heads(heads: tuple[str, ...]) -> str:
    return ", ".join(heads) if heads else "<no revision>"


def ensure_database_schema_current(engine: Engine) -> None:
    """Stop startup unless code and database heads match. There is deliberately no mutating
    fallback: a missing, unversioned, older, or newer database requires an explicit controlled
    Alembic procedure outside the application process.
    """

    expected = code_alembic_heads()
    try:
        found = database_alembic_heads(engine)
    except FileNotFoundError as exc:
        raise SchemaCompatibilityError(
            "Incompatible database schema: "
            f"expected={_describe_heads(expected)}; found=<missing database> "
            f"({exc.args[0]}). PFIM does not create databases or apply migrations at startup."
        ) from exc

    if found != expected:
        raise SchemaCompatibilityError(
            "Incompatible database schema: "
            f"expected={_describe_heads(expected)}; found={_describe_heads(found)}. "
            "PFIM does not apply migrations automatically: stop the backend and run "
            "the controlled Alembic procedure on the verified target."
        )
