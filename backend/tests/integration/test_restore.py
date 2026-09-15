"""Crash-safe restore: temporary SQLite databases and fault injection only."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.config import settings
from app.main import app
from app.maintenance import MaintenanceBusyError, MaintenanceGate, backend_instance_lock
from app.schemas.backup import RestoreRequest
from app.security import CAPABILITY_HEADER, capability_authority
from app.services.backup_service import BackupService, BackupVerificationError
from app.services.restore_service import (
    RestoreConfirmationError,
    RestoreRecoveryError,
    RestoreService,
    get_restore_operation,
    recover_pending_restore,
)

REVISION = "restore_test_revision"


class SimulatedCrash(BaseException):
    pass


def _create_database(path: Path, marker: str) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES (?)", (REVISION,))
        connection.execute("CREATE TABLE marker (value TEXT NOT NULL)")
        connection.execute("INSERT INTO marker VALUES (?)", (marker,))
        connection.commit()


def _marker(path: Path) -> str:
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as connection:
        return str(connection.execute("SELECT value FROM marker").fetchone()[0])


def _bytes(path: Path) -> bytes:
    return path.read_bytes()


@pytest.fixture
def restore_setup(tmp_path: Path):
    db_path = tmp_path / "restore.db"
    _create_database(db_path, "candidate")
    backup_service = BackupService(
        db_path=db_path,
        backup_enabled=True,
        expected_revision=REVISION,
    )
    candidate = backup_service.create_backup()
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute("UPDATE marker SET value = 'current'")
        connection.commit()
    target_engine = create_engine(f"sqlite:///{db_path}")
    request = RestoreRequest(
        request_id=uuid.uuid4(),
        expected_sha256=candidate.sha256,
        confirmation=f"RESTORE {candidate.filename}",
    )
    try:
        yield db_path, backup_service, candidate, target_engine, request
    finally:
        target_engine.dispose()


def _service(restore_setup, *, fault_hook=None) -> RestoreService:
    _, backup_service, _, target_engine, _ = restore_setup
    return RestoreService(
        backup_service=backup_service,
        engine=target_engine,
        gate=MaintenanceGate(),
        restore_enabled=True,
        quiesce_timeout=2,
        fault_hook=fault_hook,
    )


@pytest.fixture
def restore_api(restore_setup, monkeypatch: pytest.MonkeyPatch):
    db_path, _, candidate, target_engine, request = restore_setup
    import app.services.backup_service as backup_module
    import app.services.restore_service as restore_module

    monkeypatch.setattr(backup_module, "DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setattr(restore_module, "application_engine", target_engine)
    monkeypatch.setattr(settings, "backup_enabled", True)
    monkeypatch.setattr(settings, "restore_enabled", True)
    monkeypatch.setattr(settings, "expected_alembic_revision", REVISION)
    client = TestClient(
        app,
        base_url="http://localhost",
        headers={
            "Origin": "http://localhost:5173",
            CAPABILITY_HEADER: capability_authority.issue(),
        },
    )
    return client, db_path, candidate, request


def test_restore_commits_candidate_and_creates_verified_pre_restore_backup(restore_setup):
    db_path, backup_service, candidate, _, request = restore_setup

    result = _service(restore_setup).restore_backup(
        candidate.filename,
        request,
        current_request_tracked=False,
    )

    assert result.state == "completed"
    assert result.restored is True
    assert result.requires_reload is True
    assert _marker(db_path) == "candidate"
    assert result.pre_restore_backup is not None
    pre_restore = db_path.parent / result.pre_restore_backup
    assert _marker(pre_restore) == "current"
    assert backup_service._read_manifest(pre_restore) is not None
    assert not (db_path.parent / ".pfim-restore.json").exists()
    assert not list(db_path.parent.glob(".pfim-restore-*.candidate.db"))
    assert not list(db_path.parent.glob(".pfim-restore-*.rollback.db"))


def test_http_restore_exposes_eligibility_idempotency_and_operation_status(restore_api):
    client, db_path, candidate, request = restore_api
    listed = client.get("/api/v1/backup")
    status = client.get("/api/v1/backup/status")

    assert listed.status_code == 200
    selected = next(item for item in listed.json() if item["filename"] == candidate.filename)
    assert selected["restore_eligible"] is True
    assert selected["restore_ineligible_reason"] is None
    assert status.json()["restore_enabled"] is True
    response = client.post(
        f"/api/v1/backup/{candidate.filename}/restore",
        json=request.model_dump(mode="json"),
    )

    assert response.status_code == 200, response.text
    assert response.json()["state"] == "completed"
    assert _marker(db_path) == "candidate"
    operation = client.get(f"/api/v1/backup/restore-operations/{request.request_id}")
    assert operation.status_code == 200
    assert operation.json() == response.json()

    replay = client.post(
        f"/api/v1/backup/{candidate.filename}/restore",
        json=request.model_dump(mode="json"),
    )
    assert replay.status_code == 200
    assert replay.json() == response.json()
    assert len(list(db_path.parent.glob("pfim_backup_*.db"))) == 2


def test_offline_cli_uses_same_protocol_and_refuses_while_backend_lock_is_held(
    restore_setup,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
):
    db_path, _, candidate, target_engine, request = restore_setup
    import app.cli.restore as restore_cli
    import app.services.backup_service as backup_module
    import app.services.restore_service as restore_module

    monkeypatch.setattr(backup_module, "DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setattr(restore_module, "application_engine", target_engine)
    monkeypatch.setattr(restore_cli, "engine", target_engine)
    monkeypatch.setattr(restore_cli, "ensure_database_schema_current", lambda _: None)
    monkeypatch.setattr(settings, "backup_enabled", True)
    monkeypatch.setattr(settings, "restore_enabled", True)
    monkeypatch.setattr(settings, "expected_alembic_revision", REVISION)
    arguments = [
        candidate.filename,
        "--expected-sha256",
        request.expected_sha256,
        "--confirmation",
        request.confirmation,
        "--request-id",
        str(request.request_id),
    ]

    instance = backend_instance_lock(db_path.parent)
    with instance.hold(timeout=0):
        assert restore_cli.main(arguments) == 1
    error = capsys.readouterr().err
    assert "INTERPROCESS_LOCK_UNAVAILABLE" in error
    assert not list(db_path.parent.glob(".pfim-restore-operation-*.json"))

    assert restore_cli.main(arguments) == 0
    payload = capsys.readouterr().out
    assert str(request.request_id) in payload
    assert _marker(db_path) == "candidate"


def test_restore_requires_exact_server_side_confirmation(restore_setup):
    db_path, _, candidate, _, request = restore_setup
    invalid = request.model_copy(update={"confirmation": "RESTORE"})

    with pytest.raises(RestoreConfirmationError):
        _service(restore_setup).restore_backup(
            candidate.filename,
            invalid,
            current_request_tracked=False,
        )

    assert _marker(db_path) == "current"


def test_completed_request_id_is_idempotent(restore_setup):
    db_path, _, candidate, _, request = restore_setup
    service = _service(restore_setup)
    first = service.restore_backup(
        candidate.filename,
        request,
        current_request_tracked=False,
    )

    second = service.restore_backup(
        candidate.filename,
        request,
        current_request_tracked=False,
    )

    assert second == first
    assert _marker(db_path) == "candidate"
    assert len(list(db_path.parent.glob("pfim_backup_*.db"))) == 2


def test_pre_restore_backup_includes_wal_and_old_wal_never_reaches_candidate(
    restore_setup,
):
    db_path, backup_service, candidate, target_engine, request = restore_setup
    raw = target_engine.raw_connection()
    try:
        cursor = raw.cursor()
        assert cursor.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        cursor.execute("PRAGMA wal_autocheckpoint=0")
        cursor.execute("UPDATE marker SET value = 'wal-current'")
        raw.commit()
        cursor.close()
    finally:
        # Return the connection to the pool without closing its DBAPI handle: WAL
        # remains until engine.dispose(), exactly as in production.
        raw.close()
    assert Path(f"{db_path}-wal").is_file()

    result = _service(restore_setup).restore_backup(
        candidate.filename,
        request,
        current_request_tracked=False,
    )

    assert _marker(db_path) == "candidate"
    assert result.pre_restore_backup is not None
    pre_restore = db_path.parent / result.pre_restore_backup
    assert _marker(pre_restore) == "wal-current"
    assert backup_service._read_manifest(pre_restore) is not None
    # The reopened engine may create new sidecars if the restored database
    # uses WAL journal mode. The marker proves old WAL frames were not
    # applied to the candidate.
    assert not Path(f"{db_path}-journal").exists()


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_candidate_with_sqlite_sidecar_is_rejected_before_pre_restore_backup(
    restore_setup,
    suffix,
):
    db_path, backup_service, candidate, _, request = restore_setup
    candidate_path = db_path.parent / candidate.filename
    sidecar = Path(f"{candidate_path}{suffix}")
    sidecar.write_bytes(b"stale sidecar")

    listed = next(
        item for item in backup_service.list_backups() if item.filename == candidate.filename
    )
    assert listed.verified is False
    assert listed.restore_eligible is False
    assert listed.restore_ineligible_reason == "sidecars_present"

    with pytest.raises(BackupVerificationError, match="self-contained"):
        _service(restore_setup).restore_backup(
            candidate.filename,
            request,
            current_request_tracked=False,
        )

    operation = get_restore_operation(db_path.parent, request.request_id)
    assert operation.state == "failed"
    assert operation.error_code == "BACKUP_VERIFICATION_FAILED"
    assert _marker(db_path) == "current"
    assert len(list(db_path.parent.glob("pfim_backup_*.db"))) == 1
    assert sidecar.read_bytes() == b"stale sidecar"


def test_second_request_during_restore_is_failed_without_disturbing_owner(restore_setup):
    db_path, backup_service, candidate, target_engine, request = restore_setup
    gate = MaintenanceGate()
    owner_entered = threading.Event()
    release_owner = threading.Event()

    def pause_owner(point: str) -> None:
        if point == "after_pre_restore_backup":
            owner_entered.set()
            assert release_owner.wait(timeout=5)

    owner = RestoreService(
        backup_service=backup_service,
        engine=target_engine,
        gate=gate,
        restore_enabled=True,
        quiesce_timeout=2,
        fault_hook=pause_owner,
    )
    contender = RestoreService(
        backup_service=backup_service,
        engine=target_engine,
        gate=gate,
        restore_enabled=True,
        quiesce_timeout=0,
    )
    contender_request = request.model_copy(update={"request_id": uuid.uuid4()})

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            owner.restore_backup,
            candidate.filename,
            request,
            current_request_tracked=False,
        )
        assert owner_entered.wait(timeout=5)
        with pytest.raises(MaintenanceBusyError):
            contender.restore_backup(
                candidate.filename,
                contender_request,
                current_request_tracked=False,
            )
        contender_operation = get_restore_operation(db_path.parent, contender_request.request_id)
        assert contender_operation.state == "failed"
        assert contender_operation.error_code == "MAINTENANCE_BUSY"
        release_owner.set()
        assert future.result(timeout=5).state == "completed"

    assert _marker(db_path) == "candidate"


@pytest.mark.parametrize(
    "fault_point",
    [
        "after_operation_record",
        "after_pre_restore_backup",
        "after_candidate_staged",
    ],
)
def test_crash_before_durable_journal_keeps_live_and_marks_failed(
    restore_setup,
    fault_point,
):
    db_path, _, candidate, target_engine, request = restore_setup

    def crash(point: str) -> None:
        if point == fault_point:
            raise SimulatedCrash(point)

    with pytest.raises(SimulatedCrash):
        _service(restore_setup, fault_hook=crash).restore_backup(
            candidate.filename,
            request,
            current_request_tracked=False,
        )

    recover_pending_restore(
        db_path=db_path,
        engine=target_engine,
        expected_revision=REVISION,
        lock_timeout=2,
    )
    operation = get_restore_operation(db_path.parent, request.request_id)
    assert operation.state == "failed"
    assert _marker(db_path) == "current"
    assert not list(db_path.parent.glob(".pfim-restore-*.candidate.db"))
    assert not list(db_path.parent.glob(".pfim-restore-*.rollback.db"))


@pytest.mark.parametrize(
    "fault_point",
    [
        "after_journal_prepared",
        "after_engine_dispose",
        "after_sidecars_clean",
        "after_live_moved",
        "after_journal_live_moved",
        "after_candidate_installed",
        "after_candidate_validated",
    ],
)
def test_crash_before_commit_rolls_back_old_database(restore_setup, fault_point):
    db_path, _, candidate, target_engine, request = restore_setup

    def crash(point: str) -> None:
        if point == fault_point:
            raise SimulatedCrash(point)

    with pytest.raises(SimulatedCrash):
        _service(restore_setup, fault_hook=crash).restore_backup(
            candidate.filename,
            request,
            current_request_tracked=False,
        )

    recovered = recover_pending_restore(
        db_path=db_path,
        engine=target_engine,
        expected_revision=REVISION,
        lock_timeout=2,
    )
    assert recovered is not None
    assert recovered.state == "rolled_back"
    assert _marker(db_path) == "current"
    assert not (db_path.parent / ".pfim-restore.json").exists()


@pytest.mark.parametrize(
    "fault_point",
    [
        "after_journal_committed",
        "after_rollback_removed",
        "after_journal_removed",
    ],
)
def test_crash_after_commit_keeps_candidate_and_finishes_cleanup(restore_setup, fault_point):
    db_path, _, candidate, target_engine, request = restore_setup

    def crash(point: str) -> None:
        if point == fault_point:
            raise SimulatedCrash(point)

    with pytest.raises(SimulatedCrash):
        _service(restore_setup, fault_hook=crash).restore_backup(
            candidate.filename,
            request,
            current_request_tracked=False,
        )

    recover_pending_restore(
        db_path=db_path,
        engine=target_engine,
        expected_revision=REVISION,
        lock_timeout=2,
    )
    operation = get_restore_operation(db_path.parent, request.request_id)
    assert operation.state == "completed"
    assert operation.restored is True
    assert _marker(db_path) == "candidate"
    assert not (db_path.parent / ".pfim-restore.json").exists()


def test_tampered_rollback_blocks_recovery_without_moving_live_candidate(restore_setup):
    db_path, _, candidate, target_engine, request = restore_setup

    def crash(point: str) -> None:
        if point == "after_candidate_installed":
            raise SimulatedCrash(point)

    with pytest.raises(SimulatedCrash):
        _service(restore_setup, fault_hook=crash).restore_backup(
            candidate.filename,
            request,
            current_request_tracked=False,
        )
    rollback = db_path.parent / f".pfim-restore-{request.request_id.hex}.rollback.db"
    assert rollback.is_file()
    rollback.write_bytes(b"corrotto")
    live_before = _bytes(db_path)

    with pytest.raises(RestoreRecoveryError):
        recover_pending_restore(
            db_path=db_path,
            engine=target_engine,
            expected_revision=REVISION,
            lock_timeout=2,
        )

    assert _bytes(db_path) == live_before
    assert rollback.read_bytes() == b"corrotto"
    assert (db_path.parent / ".pfim-restore.json").is_file()


def test_committed_candidate_tampering_fails_closed_without_implicit_rollback(
    restore_setup,
):
    db_path, _, candidate, target_engine, request = restore_setup

    def crash(point: str) -> None:
        if point == "after_journal_committed":
            raise SimulatedCrash(point)

    with pytest.raises(SimulatedCrash):
        _service(restore_setup, fault_hook=crash).restore_backup(
            candidate.filename,
            request,
            current_request_tracked=False,
        )
    target_engine.dispose()
    rollback = db_path.parent / f".pfim-restore-{request.request_id.hex}.rollback.db"
    assert _marker(rollback) == "current"
    db_path.write_bytes(b"committed candidate tampered")

    with pytest.raises(RestoreRecoveryError):
        recover_pending_restore(
            db_path=db_path,
            engine=target_engine,
            expected_revision=REVISION,
            lock_timeout=2,
        )

    assert db_path.read_bytes() == b"committed candidate tampered"
    assert rollback.is_file()
    assert (db_path.parent / ".pfim-restore.json").is_file()


def test_recovery_can_crash_after_rollback_rename_and_resume(
    restore_setup,
    monkeypatch: pytest.MonkeyPatch,
):
    db_path, _, candidate, target_engine, request = restore_setup

    def crash_restore(point: str) -> None:
        if point == "after_candidate_installed":
            raise SimulatedCrash(point)

    with pytest.raises(SimulatedCrash):
        _service(restore_setup, fault_hook=crash_restore).restore_backup(
            candidate.filename,
            request,
            current_request_tracked=False,
        )

    import app.services.restore_service as restore_module

    real_replace = restore_module._replace_database_file
    calls = 0

    def crash_recovery_after_replace(source, destination, *, timeout):
        nonlocal calls
        real_replace(source, destination, timeout=timeout)
        calls += 1
        if calls == 2:
            raise SimulatedCrash("after_recovery_rollback_rename")

    with monkeypatch.context() as patcher:
        patcher.setattr(
            restore_module,
            "_replace_database_file",
            crash_recovery_after_replace,
        )
        with pytest.raises(SimulatedCrash):
            recover_pending_restore(
                db_path=db_path,
                engine=target_engine,
                expected_revision=REVISION,
                lock_timeout=2,
            )

    assert _marker(db_path) == "current"
    assert not (db_path.parent / f".pfim-restore-{request.request_id.hex}.rollback.db").exists()
    recovered = recover_pending_restore(
        db_path=db_path,
        engine=target_engine,
        expected_revision=REVISION,
        lock_timeout=2,
    )
    assert recovered is not None
    assert recovered.state == "rolled_back"
    assert _marker(db_path) == "current"
    assert not (db_path.parent / ".pfim-restore.json").exists()


def test_journal_operation_mismatch_fails_closed_without_mutating_live(restore_setup):
    db_path, _, candidate, target_engine, request = restore_setup

    def crash(point: str) -> None:
        if point == "after_journal_prepared":
            raise SimulatedCrash(point)

    with pytest.raises(SimulatedCrash):
        _service(restore_setup, fault_hook=crash).restore_backup(
            candidate.filename,
            request,
            current_request_tracked=False,
        )
    operation_path = db_path.parent / f".pfim-restore-operation-{request.request_id}.json"
    operation = json.loads(operation_path.read_text(encoding="utf-8"))
    operation["expected_sha256"] = "0" * 64
    operation_path.write_text(json.dumps(operation), encoding="utf-8")
    live_before = _bytes(db_path)

    with pytest.raises(RestoreRecoveryError):
        recover_pending_restore(
            db_path=db_path,
            engine=target_engine,
            expected_revision=REVISION,
            lock_timeout=2,
        )

    assert _bytes(db_path) == live_before
    assert (db_path.parent / ".pfim-restore.json").is_file()


@pytest.mark.parametrize(
    ("fault_point", "expected_marker", "expected_state"),
    [
        ("after_operation_record", "current", "failed"),
        ("after_pre_restore_backup", "current", "failed"),
        ("after_candidate_staged", "current", "failed"),
        ("after_journal_prepared", "current", "rolled_back"),
        ("after_engine_dispose", "current", "rolled_back"),
        ("after_sidecars_clean", "current", "rolled_back"),
        ("after_live_moved", "current", "rolled_back"),
        ("after_journal_live_moved", "current", "rolled_back"),
        ("after_candidate_installed", "current", "rolled_back"),
        ("after_candidate_validated", "current", "rolled_back"),
        ("after_journal_committed", "candidate", "completed"),
        ("after_rollback_removed", "candidate", "completed"),
        ("after_journal_removed", "candidate", "completed"),
    ],
)
def test_hard_process_crash_recovers_atomically_and_idempotently(
    restore_setup,
    fault_point,
    expected_marker,
    expected_state,
):
    db_path, _, candidate, target_engine, request = restore_setup
    candidate_path = db_path.parent / candidate.filename
    manifest_path = candidate_path.with_suffix(".manifest.json")
    candidate_before = _bytes(candidate_path)
    manifest_before = _bytes(manifest_path)
    backend_dir = Path(__file__).resolve().parents[2]
    worker = backend_dir / "tests" / "helpers" / "restore_crash_worker.py"

    completed = subprocess.run(
        [
            sys.executable,
            str(worker),
            str(db_path),
            candidate.filename,
            request.expected_sha256,
            str(request.request_id),
            REVISION,
            fault_point,
        ],
        cwd=backend_dir,
        env={
            **os.environ,
            "DATABASE_URL": "sqlite:///:memory:",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(backend_dir),
        },
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert completed.returncode == 86, completed.stderr

    recover_pending_restore(
        db_path=db_path,
        engine=target_engine,
        expected_revision=REVISION,
        lock_timeout=2,
    )
    operation = get_restore_operation(db_path.parent, request.request_id)
    first_live = _bytes(db_path)
    first_record = _bytes(db_path.parent / f".pfim-restore-operation-{request.request_id}.json")

    assert operation.state == expected_state
    assert _marker(db_path) == expected_marker
    assert _bytes(candidate_path) == candidate_before
    assert _bytes(manifest_path) == manifest_before
    assert not (db_path.parent / ".pfim-restore.json").exists()
    assert not list(db_path.parent.glob(".pfim-restore-*.candidate.db"))
    assert not list(db_path.parent.glob(".pfim-restore-*.rollback.db"))

    recover_pending_restore(
        db_path=db_path,
        engine=target_engine,
        expected_revision=REVISION,
        lock_timeout=2,
    )
    assert _bytes(db_path) == first_live
    assert (
        _bytes(db_path.parent / f".pfim-restore-operation-{request.request_id}.json")
        == first_record
    )
