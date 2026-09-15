"""SQLAlchemy engine, session, and declarative Base setup."""

import re
import sqlite3
from collections.abc import Generator
from pathlib import Path
from weakref import WeakSet

from fastapi import Request
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings
from app.utils.errors import DatabaseBusyError, DatabaseLockedError

BACKEND_DIR = Path(__file__).resolve().parent.parent


# SQLite URL forms that do not refer to disk files must pass through unchanged. Otherwise
# sqlite:///:memory: in .env becomes a relative path to a file named ':memory:' in
# backend/, which is invalid on Windows and fails instead of creating an in-memory
# database.
#
_NON_FILE_SQLITE_PATHS = ("", ":memory:")


def _resolve_database_url(raw_url: str) -> str:
    """Resolve relative SQLite paths against backend/, independently of the process working
    directory. Path joining preserves absolute paths, including Windows drive paths. In-memory
    databases and file: URIs with uri=true have no filesystem path to resolve or directory to
    create and pass through unchanged.
    """
    prefix = "sqlite:///"
    if not raw_url.startswith(prefix):
        return raw_url  # Other databases (such as PostgreSQL) need no path resolution.

    path_part = raw_url[len(prefix) :]
    if path_part in _NON_FILE_SQLITE_PATHS or path_part.startswith("file:"):
        return raw_url

    resolved = (BACKEND_DIR / path_part).resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return f"{prefix}{resolved}"


DATABASE_URL = _resolve_database_url(settings.database_url)
SQLITE_BUSY_TIMEOUT_MS = int(getattr(settings, "sqlite_busy_timeout_ms", 5_000))
connect_args = (
    {
        "check_same_thread": False,
        # Also set PRAGMA busy_timeout for each connection. The driver parameter prevents behavior
        # before the listener from depending on Python runtime defaults.
        #
        "timeout": SQLITE_BUSY_TIMEOUT_MS / 1_000,
    }
    if DATABASE_URL.startswith("sqlite")
    else {}
)

engine = create_engine(DATABASE_URL, connect_args=connect_args)

_SQLITE_BEGIN_MODE = "pfim_sqlite_begin_mode"
_CONFIGURED_SQLITE_ENGINES: WeakSet[Engine] = WeakSet()


def _natural_sort_key(value: str) -> tuple:
    """Case-insensitive text key that compares numeric runs as numbers. This SQLite collation
    puts Installment 2 before Installment 10. Type markers also support strings that start
    with a digit.
    """

    def chunk_key(part: str) -> tuple:
        if not part.isdigit():
            return (0, part.casefold())

        # Do not use int(part): TEXT fields have no length limit, and Python intentionally rejects
        # integers with thousands of digits. Length plus normalized digits produces the same
        # numeric order for arbitrarily large values without errors.
        #
        significant = part.lstrip("0") or "0"
        return (1, len(significant), significant)

    return tuple(chunk_key(part) for part in re.split(r"(\d+)", value))


def _natural_nocase_collation(left: str, right: str) -> int:
    left_key = _natural_sort_key(left or "")
    right_key = _natural_sort_key(right or "")
    return (left_key > right_key) - (left_key < right_key)


def configure_sqlite_engine(target_engine: Engine, *, busy_timeout_ms: int = 5_000) -> Engine:
    """Apply PFIM transaction semantics to a SQLite engine. Disable sqlite3 legacy implicit
    transaction management so SQLAlchemy always starts an explicit transaction. The execution
    option selects BEGIN for read snapshots or BEGIN IMMEDIATE for mutations, before
    check-then-write validation. File-based tests and isolated tools can reuse this public
    function to reproduce the application configuration.
    """
    if target_engine.url.get_backend_name() != "sqlite":
        return target_engine
    if target_engine in _CONFIGURED_SQLITE_ENGINES:
        return target_engine
    if busy_timeout_ms < 0:
        raise ValueError("busy_timeout_ms cannot be negative")

    @event.listens_for(target_engine, "connect")
    def _configure_connection(dbapi_connection, connection_record) -> None:
        # None disables implicit driver transaction control on all supported Python versions. The
        # begin event below always emits the requested BEGIN, regardless of the
        # LEGACY_TRANSACTION_CONTROL to PEP 249 transition planned for Python 3.16.
        #
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
        cursor.close()
        dbapi_connection.create_collation("PFIM_NATURAL_NOCASE", _natural_nocase_collation)

    @event.listens_for(target_engine, "begin")
    def _explicit_begin(connection) -> None:
        mode = connection.get_execution_options().get(_SQLITE_BEGIN_MODE, "DEFERRED")
        if mode not in {"DEFERRED", "IMMEDIATE"}:
            raise ValueError(f"Unsupported SQLite BEGIN mode: {mode}")
        statement = "BEGIN IMMEDIATE" if mode == "IMMEDIATE" else "BEGIN"
        connection.exec_driver_sql(statement)

    _CONFIGURED_SQLITE_ENGINES.add(target_engine)
    return target_engine


configure_sqlite_engine(engine, busy_timeout_ms=SQLITE_BUSY_TIMEOUT_MS)


def begin_session_transaction(db: Session, *, immediate: bool) -> None:
    """Open the request transaction immediately with the appropriate lock."""
    mode = "IMMEDIATE" if immediate else "DEFERRED"
    db.connection(execution_options={_SQLITE_BEGIN_MODE: mode})


def _translate_sqlite_lock_error(exc: OperationalError):
    """Convert only SQLite BUSY/LOCKED failures into explicit application errors."""
    original = exc.orig
    error_code = getattr(original, "sqlite_errorcode", None)
    primary_code = error_code & 0xFF if isinstance(error_code, int) else None
    message = str(original).lower()

    if primary_code == sqlite3.SQLITE_BUSY or "database is busy" in message:
        return DatabaseBusyError(
            "Database temporarily busy with another operation",
            detail={"retryable": True},
        )
    if primary_code == sqlite3.SQLITE_LOCKED or "database is locked" in message:
        return DatabaseLockedError(
            "Database locked by an internal conflict",
            detail={"retryable": False},
        )
    return None


# expire_on_commit=False keeps ORM objects readable after the end-of-request commit
# without another query. The commit occurs after the endpoint returns its objects and
# before FastAPI serializes them; expiration would clear their attributes.
#
SessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""

    pass


def get_db(request: Request) -> Generator[Session, None, None]:
    """FastAPI dependency providing one session and one transaction per request. Only this
    function commits writes. Repositories flush to expose generated IDs; services never
    commit. Composite operations are atomic: a sale, tax event, cash movement, and historical
    price either all persist or all roll back.
    """
    db = SessionLocal()
    try:
        begin_session_transaction(
            db,
            immediate=request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"},
        )
        yield db
        db.commit()
    except OperationalError as exc:
        db.rollback()
        translated = _translate_sqlite_lock_error(exc)
        if translated is not None:
            raise translated from exc
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
