"""Backup/restore: temporary SQLite databases only.

No test in this module resolves or opens ``data/pfim.db``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.security import CAPABILITY_HEADER, capability_authority
from app.services.backup_service import BackupService, BackupVerificationError

TEST_REVISION = "temp_test_revision"


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def backup_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_file = tmp_path / "pfim_test.db"
    with sqlite3.connect(db_file) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES (?)", (TEST_REVISION,))
        connection.execute("CREATE TABLE marker (value TEXT NOT NULL)")
        connection.execute("INSERT INTO marker VALUES ('initial')")

    import app.services.backup_service as backup_module

    monkeypatch.setattr(backup_module, "DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setattr(settings, "backup_enabled", True)
    monkeypatch.setattr(settings, "expected_alembic_revision", TEST_REVISION)
    monkeypatch.setattr(settings, "restore_enabled", False)

    client = TestClient(
        app,
        base_url="http://localhost",
        headers={
            "Origin": "http://localhost:5173",
            CAPABILITY_HEADER: capability_authority.issue(),
        },
    )
    yield client, db_file


def test_online_backup_is_verified_hashed_and_manifested(backup_client):
    client, db_file = backup_client

    response = client.post("/api/v1/backup")

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["verified"] is True
    assert payload["alembic_revision"] == TEST_REVISION
    assert len(payload["sha256"]) == 64

    backup_path = db_file.parent / payload["filename"]
    manifest_path = db_file.parent / payload["manifest_filename"]
    assert backup_path.is_file()
    assert manifest_path.is_file()
    assert not list(db_file.parent.glob("*.partial"))

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    response_created_at = dt.datetime.fromisoformat(payload["created_at"])
    manifest_created_at = dt.datetime.fromisoformat(manifest["created_at"])
    assert manifest["database_filename"] == backup_path.name
    assert manifest["sha256"] == file_hash(backup_path) == payload["sha256"]
    assert manifest["size_bytes"] == backup_path.stat().st_size
    assert manifest["integrity_check"] == "ok"
    assert manifest["foreign_key_violations"] == 0
    assert response_created_at.tzinfo is not None
    assert response_created_at.utcoffset() == dt.timedelta(0)
    assert manifest_created_at == response_created_at

    with sqlite3.connect(f"{backup_path.as_uri()}?mode=ro", uri=True) as copy:
        assert copy.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert copy.execute("SELECT value FROM marker").fetchone() == ("initial",)

    listed = client.get("/api/v1/backup").json()
    assert listed[0]["verified"] is True
    assert listed[0]["sha256"] == payload["sha256"]


def test_cli_backup_delegates_to_the_verified_online_service(backup_client, capsys):
    """Make/PowerShell entry points must not reintroduce raw copies."""

    _, db_file = backup_client
    from app.cli.backup import main

    assert main() == 0
    payload = json.loads(capsys.readouterr().out)
    backup_path = db_file.parent / payload["filename"]
    manifest_path = db_file.parent / payload["manifest_filename"]

    assert payload["verified"] is True
    assert backup_path.is_file()
    assert manifest_path.is_file()
    assert file_hash(backup_path) == payload["sha256"]


def test_online_backup_includes_committed_wal_frames(backup_client):
    client, db_file = backup_client
    writer = sqlite3.connect(db_file)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT INTO marker VALUES ('in-wal')")
        writer.commit()
        assert db_file.with_name(f"{db_file.name}-wal").is_file()

        payload = client.post("/api/v1/backup").json()
        backup_path = db_file.parent / payload["filename"]
        with sqlite3.connect(f"{backup_path.as_uri()}?mode=ro", uri=True) as copy:
            values = [row[0] for row in copy.execute("SELECT value FROM marker ORDER BY rowid")]
            journal_mode = copy.execute("PRAGMA journal_mode").fetchone()[0]
        assert values == ["initial", "in-wal"]
        assert journal_mode == "delete"
        assert not Path(f"{backup_path}-wal").exists()
        assert not Path(f"{backup_path}-shm").exists()
        assert not Path(f"{backup_path}-journal").exists()
    finally:
        writer.close()


def test_online_backup_is_coherent_during_delete_journal_commit(tmp_path: Path):
    """A concurrent transaction must not produce a hybrid snapshot.

    The callback pauses a sufficiently large backup after the first
    ``sqlite3_backup_step``; meanwhile, a writer commits two atomic updates
    in DELETE journal mode. The backup may represent the state before or
    after the commit, but never half of each.
    """

    db_file = tmp_path / "delete-journal.db"
    with sqlite3.connect(db_file) as connection:
        assert connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0] == "delete"
        connection.execute("CREATE TABLE alembic_version (version_num TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES (?)", (TEST_REVISION,))
        connection.execute("CREATE TABLE coherent_state (id INTEGER PRIMARY KEY, value TEXT)")
        connection.executemany(
            "INSERT INTO coherent_state(id, value) VALUES (?, 'before')",
            [(1,), (2,)],
        )
        connection.execute("CREATE TABLE payload (value BLOB NOT NULL)")
        connection.executemany(
            "INSERT INTO payload(value) VALUES (?)",
            [(b"x" * 4096,)] * 800,
        )

    paused = threading.Event()
    resume = threading.Event()
    paused_once = False

    def progress(status: int, remaining: int, total: int) -> None:
        nonlocal paused_once
        if not paused_once and remaining > 0:
            paused_once = True
            paused.set()
            assert resume.wait(timeout=10)

    service = BackupService(
        db_path=db_file,
        backup_enabled=True,
        expected_revision=TEST_REVISION,
        progress=progress,
    )
    writer = sqlite3.connect(db_file, timeout=10, check_same_thread=False)
    writer.execute("BEGIN IMMEDIATE")
    writer.execute("UPDATE coherent_state SET value = 'after'")
    commit_started = threading.Event()

    def commit_writer() -> None:
        commit_started.set()
        writer.commit()

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            backup_future = executor.submit(service.create_backup)
            assert paused.wait(timeout=10), "backup completed before the barrier"
            commit_future = executor.submit(commit_writer)
            assert commit_started.wait(timeout=2)
            resume.set()
            result = backup_future.result(timeout=20)
            commit_future.result(timeout=20)
    finally:
        resume.set()
        writer.close()

    backup_path = tmp_path / result.filename
    with sqlite3.connect(f"{backup_path.as_uri()}?mode=ro", uri=True) as copy:
        assert copy.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        values = tuple(
            row[0] for row in copy.execute("SELECT value FROM coherent_state ORDER BY id")
        )
    assert values in {("before", "before"), ("after", "after")}
    assert result.sha256 == file_hash(backup_path)


def test_revision_mismatch_aborts_without_publishing(backup_client, monkeypatch):
    client, db_file = backup_client
    monkeypatch.setattr(settings, "expected_alembic_revision", "other_build_head")

    response = client.post("/api/v1/backup")

    assert response.status_code == 409
    assert response.json()["error_code"] == "SCHEMA_REVISION_MISMATCH"
    assert not list(db_file.parent.glob("pfim_backup_*.db"))
    assert not list(db_file.parent.glob("*.partial"))


def test_foreign_key_violation_aborts_without_publishing(backup_client):
    client, db_file = backup_client
    with sqlite3.connect(db_file) as connection:
        connection.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        connection.execute("CREATE TABLE child (parent_id INTEGER REFERENCES parent(id))")
        connection.execute("INSERT INTO child VALUES (999)")

    response = client.post("/api/v1/backup")

    assert response.status_code == 500
    assert response.json()["error_code"] == "BACKUP_VERIFICATION_FAILED"
    assert not list(db_file.parent.glob("pfim_backup_*.db"))
    assert not list(db_file.parent.glob("*.partial"))


def test_validation_fault_cleans_staging_and_preserves_source(backup_client, monkeypatch):
    client, db_file = backup_client
    before = file_hash(db_file)

    def fail_validation(self, staging_path):
        raise BackupVerificationError("fault injection")

    monkeypatch.setattr(BackupService, "_validate_staging", fail_validation)
    response = client.post("/api/v1/backup")

    assert response.status_code == 500
    assert file_hash(db_file) == before
    assert not list(db_file.parent.glob("pfim_backup_*.db"))
    assert not list(db_file.parent.glob("*.partial"))


def test_publish_fault_removes_orphan_manifest_and_preserves_source(backup_client, monkeypatch):
    client, db_file = backup_client
    before = file_hash(db_file)
    calls = 0

    import app.services.backup_service as backup_module

    real_replace = backup_module.durable_replace

    def fail_database_publish(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("fault injection before database commit marker")
        return real_replace(source, destination)

    monkeypatch.setattr(backup_module, "durable_replace", fail_database_publish)
    with pytest.raises(OSError, match="fault injection"):
        client.post("/api/v1/backup")

    assert file_hash(db_file) == before
    assert not list(db_file.parent.glob("pfim_backup_*.db"))
    assert not list(db_file.parent.glob("pfim_backup_*.manifest.json"))
    assert not list(db_file.parent.glob("*.partial"))


def test_concurrent_backups_are_serialised_and_have_unique_names(tmp_path: Path):
    db_file = tmp_path / "concurrent.db"
    with sqlite3.connect(db_file) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES (?)", (TEST_REVISION,))
        connection.execute("CREATE TABLE marker (value TEXT)")
        connection.execute("INSERT INTO marker VALUES ('present')")

    service = BackupService(
        db_path=db_file,
        backup_enabled=True,
        expected_revision=TEST_REVISION,
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: service.create_backup(), range(2)))

    assert len({result.filename for result in results}) == 2
    assert all(result.verified for result in results)
    assert len(list(tmp_path.glob("pfim_backup_*.db"))) == 2
    assert not list(tmp_path.glob("*.partial"))


def test_restore_is_fail_closed_when_flag_is_not_set(backup_client):
    client, db_file = backup_client
    before = file_hash(db_file)

    response = client.post(
        "/api/v1/backup/pfim_backup_20260101_000000_000000.db/restore",
        json={
            "request_id": "f16fc2b7-1ce8-44c6-b503-b54560d0604d",
            "expected_sha256": "0" * 64,
            "confirmation": "RESTORE pfim_backup_20260101_000000_000000.db",
        },
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == "RESTORE_DISABLED"
    assert file_hash(db_file) == before


def test_backup_flag_is_fail_closed_and_visible_in_status(backup_client, monkeypatch):
    client, db_file = backup_client
    monkeypatch.setattr(settings, "backup_enabled", False)

    status = client.get("/api/v1/backup/status")
    response = client.post("/api/v1/backup")

    assert status.status_code == 200
    assert status.json()["backup_enabled"] is False
    assert status.json()["restore_enabled"] is False
    assert response.status_code == 503
    assert response.json()["error_code"] == "BACKUP_UNAVAILABLE"
    assert not list(db_file.parent.glob("pfim_backup_*.db"))


def test_list_marks_manifestless_legacy_backup_as_unverified(backup_client):
    client, db_file = backup_client
    legacy = db_file.parent / "pfim_backup_20260101_000000.db"
    legacy.write_bytes(db_file.read_bytes())

    response = client.get("/api/v1/backup")
    created_at = dt.datetime.fromisoformat(response.json()[0]["created_at"])

    assert response.status_code == 200
    assert created_at.tzinfo is not None
    assert created_at.utcoffset() == dt.timedelta(0)
    assert response.json() == [
        {
            "filename": legacy.name,
            "size_bytes": legacy.stat().st_size,
            "created_at": response.json()[0]["created_at"],
            "verified": False,
            "verification_error": "manifest_missing",
            "sha256": None,
            "alembic_revision": None,
            "manifest_filename": None,
            "restore_eligible": False,
            "restore_ineligible_reason": "not_verified",
        }
    ]


def test_download_returns_only_a_valid_backup_filename(backup_client):
    client, _ = backup_client
    payload = client.post("/api/v1/backup").json()

    response = client.get(f"/api/v1/backup/{payload['filename']}/download")

    assert response.status_code == 200
    assert payload["filename"] in response.headers["content-disposition"]
    assert response.content.startswith(b"SQLite format 3")
    manifest = client.get(f"/api/v1/backup/{payload['filename']}/manifest")
    assert manifest.status_code == 200
    assert manifest.json()["sha256"] == payload["sha256"]
    assert client.get("/api/v1/backup/pfim.db/download").status_code == 400
    assert client.get("/api/v1/backup/pfim_backup_20260101_000000.dbx/download").status_code == 400


def test_download_of_nonexistent_valid_name_returns_404(backup_client):
    client, _ = backup_client
    response = client.get("/api/v1/backup/pfim_backup_20260101_000000_000000.db/download")
    assert response.status_code == 404


def test_tampered_backup_is_not_verified_or_downloadable(backup_client):
    client, db_file = backup_client
    payload = client.post("/api/v1/backup").json()
    backup_path = db_file.parent / payload["filename"]
    with backup_path.open("ab") as stream:
        stream.write(b"tampered")

    listed = client.get("/api/v1/backup").json()
    database_download = client.get(f"/api/v1/backup/{payload['filename']}/download")
    manifest_download = client.get(f"/api/v1/backup/{payload['filename']}/manifest")

    assert listed[0]["verified"] is False
    assert listed[0]["sha256"] is None
    assert database_download.status_code == 500
    assert database_download.json()["error_code"] == "BACKUP_VERIFICATION_FAILED"
    assert manifest_download.status_code == 500


def test_only_stale_strictly_named_orphans_are_cleaned(backup_client):
    client, db_file = backup_client
    old_partial = db_file.parent / (".pfim_backup_20260101_000000_000000_deadbeef.db.partial")
    old_manifest = db_file.parent / ("pfim_backup_20260101_000000_000000_deadbeef.manifest.json")
    recent_partial = db_file.parent / (".pfim_backup_20260101_000000_000000_cafebabe.db.partial")
    unrelated = db_file.parent / ".pfim_backup_notes.partial"
    for path in (old_partial, old_manifest, recent_partial, unrelated):
        path.write_text("orphan", encoding="utf-8")
    old_timestamp = dt.datetime.now(dt.UTC).timestamp() - 25 * 60 * 60
    os.utime(old_partial, (old_timestamp, old_timestamp))
    os.utime(old_manifest, (old_timestamp, old_timestamp))

    response = client.post("/api/v1/backup")

    assert response.status_code == 201
    assert not old_partial.exists()
    assert not old_manifest.exists()
    assert recent_partial.exists()
    assert unrelated.exists()
