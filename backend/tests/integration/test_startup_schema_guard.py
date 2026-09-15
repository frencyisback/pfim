"""FastAPI lifespan rejects a database with an incompatible revision."""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import closing

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

import app.main as main_module
from app.config import settings
from app.maintenance import MaintenanceGate
from app.schema_guard import SchemaCompatibilityError
from app.schemas.backup import RestoreRequest
from app.services.backup_service import BackupService
from app.services.restore_service import RestoreService, get_restore_operation

HEAD = "d7b2e9f4a6c1"


class SimulatedCrash(BaseException):
    pass


def _set_revision(path, revision: str) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE alembic_version " "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
        )
        connection.execute("INSERT INTO alembic_version VALUES (?)", (revision,))


def test_lifespan_stops_before_serving_requests_on_schema_mismatch(tmp_path, monkeypatch):
    database = tmp_path / "outdated.db"
    _set_revision(database, "b7e4d1c9a3f2")
    target_engine = create_engine(f"sqlite:///{database}")
    monkeypatch.setattr(main_module, "engine", target_engine)

    try:
        with (
            pytest.raises(SchemaCompatibilityError, match=f"expected={HEAD}"),
            TestClient(main_module.app, base_url="http://localhost"),
        ):
            pytest.fail("lifespan must not begin serving requests")
    finally:
        target_engine.dispose()


def test_lifespan_serves_health_only_after_exact_schema_match(tmp_path, monkeypatch):
    database = tmp_path / "current.db"
    _set_revision(database, HEAD)
    target_engine = create_engine(f"sqlite:///{database}")
    monkeypatch.setattr(main_module, "engine", target_engine)

    try:
        with TestClient(main_module.app, base_url="http://localhost") as client:
            response = client.get("/api/v1/health")
    finally:
        target_engine.dispose()

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_lifespan_recovers_restore_journal_before_running_schema_guard(tmp_path, monkeypatch):
    database = tmp_path / "recover-before-guard.db"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES (?)", (HEAD,))
        connection.execute("CREATE TABLE marker (value TEXT NOT NULL)")
        connection.execute("INSERT INTO marker VALUES ('candidate')")
        connection.commit()
    backup_service = BackupService(
        db_path=database,
        backup_enabled=True,
        expected_revision=HEAD,
    )
    candidate = backup_service.create_backup()
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("UPDATE marker SET value = 'current'")
        connection.commit()
    target_engine = create_engine(f"sqlite:///{database}")
    request = RestoreRequest(
        request_id=uuid.uuid4(),
        expected_sha256=candidate.sha256,
        confirmation=f"RESTORE {candidate.filename}",
    )

    def crash(point: str) -> None:
        if point == "after_live_moved":
            raise SimulatedCrash(point)

    service = RestoreService(
        backup_service=backup_service,
        engine=target_engine,
        gate=MaintenanceGate(),
        restore_enabled=True,
        quiesce_timeout=2,
        fault_hook=crash,
    )
    with pytest.raises(SimulatedCrash):
        service.restore_backup(
            candidate.filename,
            request,
            current_request_tracked=False,
        )
    assert not database.exists()

    monkeypatch.setattr(main_module, "engine", target_engine)
    monkeypatch.setattr(settings, "expected_alembic_revision", HEAD)
    try:
        with TestClient(main_module.app, base_url="http://localhost") as client:
            response = client.get("/api/v1/health")
    finally:
        target_engine.dispose()

    with closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as connection:
        marker = connection.execute("SELECT value FROM marker").fetchone()[0]
    operation = get_restore_operation(database.parent, request.request_id)
    assert response.status_code == 200
    assert marker == "current"
    assert operation.state == "rolled_back"
    assert not (database.parent / ".pfim-restore.json").exists()
