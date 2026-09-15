"""A19/A20: only synthetic backups and databases from temporary fixtures."""

import datetime as dt
import json
import sqlite3
from contextlib import closing

import pytest
from pydantic import ValidationError

from app.config import Settings, settings
from app.maintenance import operation_lock
from app.services.backup_service import BackupService, BackupTimeoutError
from app.services.restore_service import RestoreConflictError, get_restore_operation
from tests.integration.test_backup import TEST_REVISION
from tests.integration.test_backup import backup_client as backup_client
from tests.integration.test_backup import file_hash
from tests.integration.test_restore import _service
from tests.integration.test_restore import restore_setup as restore_setup


@pytest.mark.parametrize(
    "replacement",
    [
        [],
        None,
        "text",
        12,
        {"format_version": True},
        {"format_version": 2},
        {"size_bytes": True},
        {"size_bytes": "16384"},
        {"size_bytes": -1},
        {"foreign_key_violations": False},
        {"foreign_key_violations": 1},
        {"sha256": []},
        {"sha256": "invalid"},
        {"created_at": "invalid"},
        {"created_at": "2026-09-09T12:00:00"},
        {"created_at": None},
        {"alembic_revision": " "},
    ],
)
def test_bad_manifest_stays_visible_without_blocking_healthy_backups(backup_client, replacement):
    client, db_file = backup_client
    healthy = client.post("/api/v1/backup").json()
    target = client.post("/api/v1/backup").json()
    manifest_path = db_file.parent / target["manifest_filename"]
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if isinstance(replacement, dict):
        payload.update(replacement)
    else:
        payload = replacement
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    original_bytes = manifest_path.read_bytes()

    response = client.get("/api/v1/backup")
    assert response.status_code == 200
    entries = {entry["filename"]: entry for entry in response.json()}
    assert entries[healthy["filename"]]["verified"] is True
    invalid = entries[target["filename"]]
    assert invalid["verified"] is False
    assert invalid["verification_error"] == "manifest_invalid"
    assert invalid["restore_eligible"] is False
    assert dt.datetime.fromisoformat(invalid["created_at"]).tzinfo is not None
    for action in ("download", "manifest"):
        assert client.get(f"/api/v1/backup/{target['filename']}/{action}").status_code == 500
    assert manifest_path.read_bytes() == original_bytes


@pytest.mark.parametrize("manifest_kind", ["file", "directory"])
def test_legacy_with_malformed_manifest_is_not_downloadable(backup_client, manifest_kind):
    client, db_file = backup_client
    path = db_file.parent / "pfim_backup_20260101_000000.db"
    path.write_bytes(db_file.read_bytes())
    manifest = path.with_suffix(".manifest.json")
    if manifest_kind == "file":
        manifest.write_text("[]", encoding="utf-8")
    else:
        manifest.mkdir()
    response = client.get("/api/v1/backup")
    assert response.status_code == 200
    assert response.json()[0]["verification_error"] == "manifest_invalid"
    assert client.get(f"/api/v1/backup/{path.name}/download").status_code == 500


def test_manifest_date_is_normalized_only_in_memory(backup_client):
    client, db_file = backup_client
    target = client.post("/api/v1/backup").json()
    manifest_path = db_file.parent / target["manifest_filename"]
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["created_at"] = "2026-09-09T12:00:00+02:00"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    before = manifest_path.read_bytes()
    response = client.get("/api/v1/backup")
    assert response.status_code == 200
    assert response.json()[0]["verified"] is True
    assert response.json()[0]["created_at"] == "2026-09-09T10:00:00Z"
    assert manifest_path.read_bytes() == before


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


def _clock(monkeypatch):
    import app.services.backup_service as module

    clock = Clock()
    monkeypatch.setattr(module, "monotonic", clock)
    monkeypatch.setattr(settings, "backup_copy_timeout_seconds", 1)
    return clock


def test_copy_deadline_aborts_even_without_contention_and_cleans_only_staging(
    backup_client, monkeypatch
):
    client, db_file = backup_client
    previous = client.post("/api/v1/backup").json()
    previous_path = db_file.parent / previous["filename"]
    previous_hash, source_hash = file_hash(previous_path), file_hash(db_file)
    clock = _clock(monkeypatch)

    def slow_progress(*_):
        clock.now += 2

    service = BackupService(
        db_path=db_file,
        backup_enabled=True,
        expected_revision=TEST_REVISION,
        progress=slow_progress,
    )
    with pytest.raises(BackupTimeoutError):
        service.create_backup()
    assert file_hash(previous_path) == previous_hash
    assert file_hash(db_file) == source_hash
    assert list(db_file.parent.glob("pfim_backup_*.db")) == [previous_path]
    assert not list(db_file.parent.glob("*.partial*"))
    with operation_lock(db_file.parent).hold(timeout=0):
        pass


@pytest.mark.parametrize("release_lock", [False, True])
def test_copy_busy_retries_have_a_deadline_but_transient_contention_can_succeed(
    backup_client, monkeypatch, release_lock
):
    _, db_file = backup_client
    source_hash = file_hash(db_file)
    clock = _clock(monkeypatch)
    statuses = []
    with closing(sqlite3.connect(db_file)) as locker:
        locker.execute("BEGIN EXCLUSIVE")

        def progress(status, *_):
            statuses.append(status)
            if status in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                clock.now += 0.4
                if release_lock:
                    locker.rollback()

        service = BackupService(
            db_path=db_file, backup_enabled=True, expected_revision=TEST_REVISION, progress=progress
        )
        if release_lock:
            result = service.create_backup()
            assert result.verified
        else:
            with pytest.raises(BackupTimeoutError):
                service.create_backup()
        locker.rollback()
    assert sqlite3.SQLITE_BUSY in statuses or sqlite3.SQLITE_LOCKED in statuses
    assert file_hash(db_file) == source_hash
    assert not list(db_file.parent.glob("*.partial*"))


def test_timeout_before_restore_leaves_live_and_gate_intact_and_request_id_terminal(
    restore_setup, monkeypatch
):
    db_path, backup_service, candidate, _, request = restore_setup
    before = db_path.read_bytes()
    clock = _clock(monkeypatch)
    calls = []

    def slow_progress(*_):
        calls.append(1)
        clock.now += 2

    monkeypatch.setattr(backup_service, "_progress", slow_progress)
    service = _service(restore_setup)
    with pytest.raises(BackupTimeoutError):
        service.restore_backup(candidate.filename, request, current_request_tracked=False)
    assert db_path.read_bytes() == before
    result = get_restore_operation(db_path.parent, str(request.request_id))
    assert result.state == "failed"
    assert result.error_code == "BACKUP_TIMEOUT"
    assert not result.restored
    assert result.pre_restore_backup is None
    assert not (db_path.parent / ".pfim-restore.json").exists()
    assert not list(db_path.parent.glob("*.partial*"))
    assert service.gate.enter_request()
    service.gate.leave_request()
    with operation_lock(db_path.parent).hold(timeout=0):
        pass
    with pytest.raises(RestoreConflictError) as repeated:
        service.restore_backup(candidate.filename, request, current_request_tracked=False)
    assert repeated.value.detail["state"] == "failed"
    assert repeated.value.detail["error_code"] == "BACKUP_TIMEOUT"
    assert len(calls) == 1


def test_timeout_is_a_structured_http_error(backup_client, monkeypatch):
    client, _ = backup_client

    def expired(*_):
        raise BackupTimeoutError("Backup copy timed out")

    monkeypatch.setattr(BackupService, "_online_copy", expired)
    response = client.post("/api/v1/backup")
    assert response.status_code == 503
    assert response.json()["error_code"] == "BACKUP_TIMEOUT"
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


@pytest.mark.parametrize("value", [0, -1, 601])
def test_copy_timeout_setting_rejects_unbounded_or_nonpositive_limits(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, backup_copy_timeout_seconds=value)
