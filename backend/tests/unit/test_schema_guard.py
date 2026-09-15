"""The startup guard reads revisions and never modifies the database."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.schema_guard import (
    SchemaCompatibilityError,
    code_alembic_heads,
    database_alembic_heads,
    ensure_database_schema_current,
)

HEAD = "d7b2e9f4a6c1"
OLD_REVISION = "b7e4d1c9a3f2"
SIDECAR_SUFFIXES = ("-journal", "-wal", "-shm")


def _versioned_database(path: Path, revision: str) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE alembic_version " "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
        )
        connection.execute(
            "INSERT INTO alembic_version (version_num) VALUES (?)",
            (revision,),
        )
        connection.execute("CREATE TABLE preserved_data (value TEXT NOT NULL)")
        connection.execute("INSERT INTO preserved_data VALUES ('unchanged')")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sidecars(path: Path) -> set[Path]:
    return {
        Path(f"{path}{suffix}") for suffix in SIDECAR_SUFFIXES if Path(f"{path}{suffix}").exists()
    }


def test_code_head_is_the_exact_distributed_alembic_head():
    assert code_alembic_heads() == (HEAD,)


def test_mismatch_is_read_only_and_never_calls_upgrade(tmp_path, monkeypatch):
    database = tmp_path / "outdated.db"
    _versioned_database(database, OLD_REVISION)
    before_hash = _sha256(database)
    before_mtime = database.stat().st_mtime_ns
    before_sidecars = _sidecars(database)
    upgrade_calls = 0

    def forbidden_upgrade(*args, **kwargs):
        nonlocal upgrade_calls
        upgrade_calls += 1
        raise AssertionError("the guard must not invoke alembic upgrade")

    monkeypatch.setattr(command, "upgrade", forbidden_upgrade)
    target_engine = create_engine(f"sqlite:///{database}")
    try:
        with pytest.raises(SchemaCompatibilityError) as raised:
            ensure_database_schema_current(target_engine)
    finally:
        target_engine.dispose()

    message = str(raised.value)
    assert f"expected={HEAD}" in message
    assert f"found={OLD_REVISION}" in message
    assert "does not apply migrations automatically" in message
    assert upgrade_calls == 0
    assert _sha256(database) == before_hash
    assert database.stat().st_mtime_ns == before_mtime
    assert _sidecars(database) == before_sidecars == set()


def test_missing_sqlite_database_is_not_created(tmp_path):
    database = tmp_path / "does-not-exist.db"
    target_engine = create_engine(f"sqlite:///{database}")
    try:
        with pytest.raises(SchemaCompatibilityError) as raised:
            ensure_database_schema_current(target_engine)
    finally:
        target_engine.dispose()

    assert "found=<missing database>" in str(raised.value)
    assert not database.exists()
    assert _sidecars(database) == set()


def test_current_file_database_passes(tmp_path):
    database = tmp_path / "current.db"
    _versioned_database(database, HEAD)
    target_engine = create_engine(f"sqlite:///{database}")
    try:
        ensure_database_schema_current(target_engine)
    finally:
        target_engine.dispose()


def test_in_memory_database_uses_the_owning_engine_connection():
    target_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    try:
        with target_engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE alembic_version " "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
            )
            connection.exec_driver_sql(
                "INSERT INTO alembic_version (version_num) VALUES (?)",
                (HEAD,),
            )

        assert database_alembic_heads(target_engine) == (HEAD,)
        ensure_database_schema_current(target_engine)
    finally:
        target_engine.dispose()
