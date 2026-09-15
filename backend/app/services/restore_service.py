"""Crash-safe SQLite restore with a persistent journal and deterministic recovery. The durable
committed record is the sole commit point. Before it is synced, recovery restores the previous
database; afterward it keeps the validated candidate and completes cleanup.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.config import settings
from app.database import engine as application_engine
from app.maintenance import (
    MaintenanceGate,
    durable_replace,
    maintenance_gate,
    operation_lock,
)
from app.schemas.backup import RestoreRequest, RestoreResult
from app.services.backup_service import (
    BackupService,
    BackupUnavailableError,
    BackupVerificationError,
    RestoreDisabledError,
    SchemaRevisionMismatchError,
    _fsync_directory,
    _fsync_file,
    _readonly_uri,
    _sha256,
    is_valid_backup_filename,
)
from app.utils.errors import NotFoundError, PFIMError, ValidationErrorPFIM

_JOURNAL_FILENAME = ".pfim-restore.json"
_JOURNAL_FORMAT_VERSION = 1
_OPERATION_FORMAT_VERSION = 1
_OPERATION_PATTERN = re.compile(
    r"^\.pfim-restore-operation-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12})\.json$"
)
_PHASES = frozenset({"prepared", "live_moved", "committed"})
_TERMINAL_STATES = frozenset({"completed", "rolled_back", "failed"})
_SQLITE_HEADER = b"SQLite format 3\x00"
_REQUEST_REGISTRATION_LOCK = threading.Lock()


class RestoreConfirmationError(ValidationErrorPFIM):
    error_code = "RESTORE_CONFIRMATION_INVALID"


class RestoreConflictError(PFIMError):
    status_code = 409
    error_code = "RESTORE_REQUEST_CONFLICT"


class RestoreInProgressError(PFIMError):
    status_code = 409
    error_code = "RESTORE_IN_PROGRESS"


class RestoreFailedError(PFIMError):
    status_code = 500
    error_code = "RESTORE_FAILED"


class RestoreRecoveryError(PFIMError):
    """The process cannot serve requests until recovery succeeds."""

    status_code = 503
    error_code = "RESTORE_RECOVERY_REQUIRED"


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _journal_path(data_dir: Path) -> Path:
    return data_dir / _JOURNAL_FILENAME


def _operation_path(data_dir: Path, operation_id: uuid.UUID | str) -> Path:
    canonical = str(uuid.UUID(str(operation_id)))
    return data_dir / f".pfim-restore-operation-{canonical}.json"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.partial")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        durable_replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise RestoreRecoveryError(f"A restore record cannot be a symlink: {path.name}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RestoreRecoveryError(f"Unreadable restore record: {path.name}") from exc
    if not isinstance(payload, dict):
        raise RestoreRecoveryError(f"Invalid restore record: {path.name}")
    return payload


def _write_operation(data_dir: Path, result: RestoreResult) -> None:
    payload = {
        "format_version": _OPERATION_FORMAT_VERSION,
        **result.model_dump(mode="json"),
    }
    _atomic_write_json(_operation_path(data_dir, result.operation_id), payload)


def get_restore_operation(data_dir: Path, operation_id: uuid.UUID | str) -> RestoreResult:
    canonical = uuid.UUID(str(operation_id))
    path = _operation_path(data_dir, canonical)
    if not path.is_file():
        raise NotFoundError(
            f"Restore operation '{operation_id}' not found",
            detail={"operation_id": str(operation_id)},
        )
    payload = _read_json(path)
    if payload.get("format_version") != _OPERATION_FORMAT_VERSION:
        raise RestoreRecoveryError(f"Unsupported restore operation format: {path.name}")
    try:
        result = RestoreResult.model_validate(payload)
    except (TypeError, ValueError) as exc:
        raise RestoreRecoveryError(f"Invalid restore operation: {path.name}") from exc
    if result.operation_id != canonical:
        raise RestoreRecoveryError("The operation ID in the record does not match the filename")
    return result


def _list_operation_paths(data_dir: Path) -> list[Path]:
    if not data_dir.is_dir():
        return []
    return sorted(
        (
            path
            for path in data_dir.iterdir()
            if path.is_file() and _OPERATION_PATTERN.fullmatch(path.name)
        ),
        key=lambda path: path.name,
    )


def restore_runtime_status(data_dir: Path) -> dict[str, object]:
    gate = maintenance_gate.snapshot()
    journal = _journal_path(data_dir)
    if journal.is_file():
        try:
            payload = _read_json(journal)
            operation_id = str(uuid.UUID(str(payload["operation_id"])))
            operation = get_restore_operation(data_dir, operation_id)
            return {
                "maintenance_mode": True,
                "restore_state": "failed" if gate["poisoned"] else operation.state,
                "active_restore_id": operation_id,
            }
        except (KeyError, ValueError, RestoreRecoveryError):
            return {
                "maintenance_mode": True,
                "restore_state": "failed",
                "active_restore_id": gate.get("active_restore_id"),
            }
    active_restore_id = gate["active_restore_id"]
    if active_restore_id is not None:
        try:
            operation = get_restore_operation(data_dir, str(active_restore_id))
            restore_state = operation.state
        except (PFIMError, ValueError):
            restore_state = "recovering" if gate["poisoned"] else "preparing"
    else:
        restore_state = "recovering" if gate["poisoned"] else "idle"
    return {
        "maintenance_mode": bool(gate["maintenance_mode"]),
        "restore_state": restore_state,
        "active_restore_id": active_restore_id,
    }


def _database_sidecars(path: Path) -> tuple[Path, ...]:
    return tuple(Path(f"{path}{suffix}") for suffix in ("-wal", "-shm", "-journal"))


def _reject_database_sidecars(path: Path, *, label: str) -> None:
    present = [sidecar.name for sidecar in _database_sidecars(path) if sidecar.exists()]
    if present:
        raise BackupVerificationError(
            f"{label} is not a self-contained SQLite file",
            detail={"sidecars": present},
        )


def _validate_database(path: Path, expected_revision: str) -> str:
    try:
        with path.open("rb") as stream:
            if stream.read(len(_SQLITE_HEADER)) != _SQLITE_HEADER:
                raise BackupVerificationError("Invalid candidate SQLite header")
        with closing(
            sqlite3.connect(
                _readonly_uri(path),
                uri=True,
                timeout=settings.sqlite_busy_timeout_ms / 1000,
            )
        ) as connection:
            connection.execute("PRAGMA query_only = ON")
            integrity_rows = [row[0] for row in connection.execute("PRAGMA integrity_check")]
            if integrity_rows != ["ok"]:
                raise BackupVerificationError(
                    "SQLite integrity check failed",
                    detail={"results": integrity_rows[:10]},
                )
            violation = connection.execute("PRAGMA foreign_key_check").fetchone()
            if violation is not None:
                raise BackupVerificationError(
                    "SQLite foreign-key check failed",
                    detail={"first_violation": list(violation)},
                )
            revisions = [
                row[0]
                for row in connection.execute(
                    "SELECT version_num FROM alembic_version ORDER BY version_num"
                )
            ]
    except (BackupVerificationError, SchemaRevisionMismatchError):
        raise
    except (OSError, sqlite3.Error) as exc:
        raise BackupVerificationError("Cannot verify the restore database") from exc

    if revisions != [expected_revision]:
        raise SchemaRevisionMismatchError(
            "The restore database revision does not match the expected revision",
            detail={"expected": expected_revision, "found": revisions},
        )
    return revisions[0]


def _copy_sqlite_snapshot(source_path: Path, destination_path: Path) -> None:
    if os.path.lexists(destination_path):
        raise RestoreRecoveryError(f"Restore staging already exists: {destination_path.name}")
    try:
        with closing(
            sqlite3.connect(
                _readonly_uri(source_path),
                uri=True,
                timeout=settings.sqlite_busy_timeout_ms / 1000,
            )
        ) as source, closing(
            sqlite3.connect(destination_path, timeout=settings.sqlite_busy_timeout_ms / 1000)
        ) as destination:
            source.backup(destination, pages=256, sleep=0.05)
            checkpoint = destination.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if checkpoint is not None and int(checkpoint[0]) != 0:
                raise BackupVerificationError(
                    "Restore staging WAL checkpoint failed",
                    detail={"checkpoint": list(checkpoint)},
                )
            journal_mode = destination.execute("PRAGMA journal_mode=DELETE").fetchone()
            if journal_mode is None or str(journal_mode[0]).lower() != "delete":
                raise BackupVerificationError("Cannot make restore staging self-contained")
            destination.commit()
    except BackupVerificationError:
        raise
    except sqlite3.Error as exc:
        raise BackupVerificationError("Cannot prepare the restore candidate") from exc
    _reject_database_sidecars(destination_path, label="Restore staging")
    _fsync_file(destination_path)
    _fsync_directory(destination_path.parent)


def _engine_database_path(engine: Engine) -> Path:
    if engine.url.get_backend_name() != "sqlite" or engine.url.database in {
        None,
        "",
        ":memory:",
    }:
        raise BackupUnavailableError("Restore is supported only for file-based SQLite databases")
    return Path(str(engine.url.database)).resolve()


def _remove_file(path: Path) -> None:
    path.unlink(missing_ok=True)
    _fsync_directory(path.parent)


def _replace_database_file(source: Path, destination: Path, *, timeout: float) -> None:
    """Retry only transient Windows sharing violations. Persistent external handles still abort
    before commit; retries cover brief SQLite or antivirus descriptor-closing delays after
    checkpoints.
    """

    deadline = time.monotonic() + timeout
    while True:
        try:
            durable_replace(source, destination)
            return
        except OSError as exc:
            if getattr(exc, "winerror", None) not in {5, 32, 33}:
                raise
            if time.monotonic() >= deadline:
                raise BackupUnavailableError(
                    "The SQLite file is still open in another process",
                    detail={"retryable": True, "source": source.name},
                ) from exc
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))


class RestoreService:
    def __init__(
        self,
        *,
        backup_service: BackupService | None = None,
        engine: Engine | None = None,
        gate: MaintenanceGate = maintenance_gate,
        restore_enabled: bool | None = None,
        quiesce_timeout: float | None = None,
        fault_hook: Callable[[str], None] | None = None,
    ) -> None:
        self.backup_service = backup_service or BackupService()
        self.db_path = self.backup_service.db_path
        self.data_dir = self.db_path.parent
        self.expected_revision = self.backup_service.expected_revision
        self.engine = application_engine if engine is None else engine
        self.gate = gate
        self.restore_enabled = (
            settings.restore_enabled if restore_enabled is None else restore_enabled
        )
        self.quiesce_timeout = (
            float(settings.restore_quiesce_timeout_seconds)
            if quiesce_timeout is None
            else quiesce_timeout
        )
        self._fault_hook = fault_hook

    def _fault(self, point: str) -> None:
        if self._fault_hook is not None:
            self._fault_hook(point)

    def _ensure_enabled(self) -> None:
        if not self.restore_enabled:
            raise RestoreDisabledError(
                "Restore is disabled in the configuration",
                detail={"setting": "RESTORE_ENABLED"},
            )
        if not self.backup_service.backup_enabled or not self.expected_revision:
            raise RestoreDisabledError(
                "Restore requires verified backups and a configured Alembic revision",
                detail={
                    "backup_enabled": self.backup_service.backup_enabled,
                    "expected_revision_configured": bool(self.expected_revision),
                },
            )
        if not self.db_path.is_file():
            raise RestoreDisabledError("Operational database not found")
        engine_path = _engine_database_path(self.engine)
        if engine_path != self.db_path:
            raise RestoreDisabledError(
                "The application engine and restore database do not match",
                detail={"engine_database": str(engine_path), "restore_database": str(self.db_path)},
            )

    def _existing_idempotent_result(
        self,
        filename: str,
        request: RestoreRequest,
    ) -> RestoreResult | None:
        path = _operation_path(self.data_dir, request.request_id)
        if not path.is_file():
            return None
        result = get_restore_operation(self.data_dir, request.request_id)
        if result.restored_backup != filename or result.expected_sha256 != request.expected_sha256:
            raise RestoreConflictError(
                "request_id has already been used with different parameters",
                detail={"operation_id": str(request.request_id)},
            )
        if result.state == "completed":
            return result
        if result.state not in _TERMINAL_STATES:
            raise RestoreInProgressError(
                "A restore with this request_id is still in progress",
                detail=result.model_dump(mode="json"),
            )
        raise RestoreConflictError(
            "The previous attempt with this request_id has not completed",
            detail=result.model_dump(mode="json"),
        )

    def _validate_candidate(self, filename: str, expected_sha256: str) -> dict[str, Any]:
        if not is_valid_backup_filename(filename):
            raise ValidationErrorPFIM(
                "Invalid backup filename",
                detail={"filename": filename},
            )
        candidate = self.backup_service.get_backup_path(filename)
        _reject_database_sidecars(candidate, label="The selected backup")
        manifest = self.backup_service._read_manifest(candidate)
        if manifest is None:
            raise BackupVerificationError(
                "Restore is allowed only from a backup with a verified manifest",
                detail={"filename": filename},
            )
        if manifest["sha256"] != expected_sha256:
            raise RestoreConflictError(
                "The selected backup has changed since confirmation",
                detail={"expected": expected_sha256, "found": manifest["sha256"]},
            )
        if manifest["alembic_revision"] != self.expected_revision:
            raise SchemaRevisionMismatchError(
                "Backup is incompatible with the current build revision",
                detail={
                    "expected": self.expected_revision,
                    "found": manifest["alembic_revision"],
                },
            )
        _validate_database(candidate, self.expected_revision)
        return manifest

    def _stage_candidate(
        self,
        candidate: Path,
        staging: Path,
        expected_sha256: str,
    ) -> str:
        before = self._validate_candidate(candidate.name, expected_sha256)
        _copy_sqlite_snapshot(candidate, staging)
        _validate_database(staging, self.expected_revision)
        staged_sha256 = _sha256(staging)
        after = self._validate_candidate(candidate.name, expected_sha256)
        if before != after:
            raise BackupVerificationError("The restore candidate changed during staging")
        return staged_sha256

    def _dispose_engine(self) -> None:
        self.engine.dispose()

    def _reopen_engine(self, expected_revision: str) -> None:
        if _engine_database_path(self.engine) != self.db_path:
            raise RestoreRecoveryError("The engine reopened a database different from the target")
        with self.engine.connect() as connection:
            revisions = tuple(
                row[0]
                for row in connection.execute(
                    text("SELECT version_num FROM alembic_version ORDER BY version_num")
                )
            )
        if revisions != (expected_revision,):
            raise RestoreRecoveryError(
                f"Engine reopened with an unexpected revision: {revisions!r}"
            )

    def _checkpoint_and_detach_live(self) -> None:
        uri = f"{self.db_path.resolve().as_uri()}?mode=rw"
        try:
            with closing(
                sqlite3.connect(
                    uri,
                    uri=True,
                    timeout=settings.sqlite_busy_timeout_ms / 1000,
                )
            ) as connection:
                checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                if checkpoint is not None and int(checkpoint[0]) != 0:
                    raise BackupUnavailableError(
                        "WAL checkpoint busy: restore cancelled",
                        detail={"checkpoint": list(checkpoint), "retryable": True},
                    )
                integrity = connection.execute("PRAGMA integrity_check").fetchall()
                if integrity != [("ok",)]:
                    raise BackupVerificationError(
                        "The operational database failed integrity checks before restore",
                        detail={"results": [row[0] for row in integrity[:10]]},
                    )
        except (BackupUnavailableError, BackupVerificationError):
            raise
        except sqlite3.Error as exc:
            raise BackupUnavailableError(
                "Cannot quiesce SQLite",
                detail={"retryable": True},
            ) from exc

        journal = Path(f"{self.db_path}-journal")
        if journal.exists():
            raise BackupUnavailableError(
                "A rollback journal remains after quiescence",
                detail={"sidecar": journal.name},
            )
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{self.db_path}{suffix}")
            try:
                sidecar.unlink(missing_ok=True)
            except OSError as exc:
                raise BackupUnavailableError(
                    "External SQLite connections prevent restore",
                    detail={"sidecar": sidecar.name, "retryable": True},
                ) from exc
        _fsync_file(self.db_path)
        _fsync_directory(self.data_dir)

    def _new_operation(self, filename: str, request: RestoreRequest) -> RestoreResult:
        return RestoreResult(
            operation_id=request.request_id,
            state="preparing",
            restored=False,
            restored_backup=filename,
            expected_sha256=request.expected_sha256,
            pre_restore_backup=None,
            alembic_revision=self.expected_revision,
            started_at=_utcnow(),
            completed_at=None,
            requires_reload=False,
        )

    def _mark_unjournaled_failure(self, operation_id: str, exc: Exception) -> None:
        if _journal_path(self.data_dir).exists():
            return
        try:
            result = get_restore_operation(self.data_dir, operation_id)
        except (PFIMError, RestoreRecoveryError, ValueError):
            return
        if result.state in _TERMINAL_STATES and not (
            result.state == "failed" and result.error_code == "RESTORE_INTERRUPTED_BEFORE_SWAP"
        ):
            return
        error_code = exc.error_code if isinstance(exc, PFIMError) else "RESTORE_FAILED"
        result = result.model_copy(
            update={
                "state": "failed",
                "restored": False,
                "completed_at": _utcnow(),
                "error_code": error_code,
                "message": str(exc),
            }
        )
        _write_operation(self.data_dir, result)

    @contextmanager
    def _exclusive_restore_context(self, operation_id: str, *, current_request_tracked: bool):
        try:
            with self.gate.exclusive(
                operation_id,
                current_request_tracked=current_request_tracked,
                timeout=self.quiesce_timeout,
            ), operation_lock(self.data_dir).hold(timeout=self.quiesce_timeout):
                yield
        except Exception as exc:
            self._mark_unjournaled_failure(operation_id, exc)
            raise

    def restore_backup(
        self,
        filename: str,
        request: RestoreRequest,
        *,
        current_request_tracked: bool = True,
    ) -> RestoreResult:
        self._ensure_enabled()
        expected_confirmation = f"RESTORE {filename}"
        if request.confirmation != expected_confirmation:
            raise RestoreConfirmationError(
                "Invalid restore confirmation",
                detail={"expected": expected_confirmation},
            )
        with _REQUEST_REGISTRATION_LOCK:
            existing = self._existing_idempotent_result(filename, request)
            if existing is not None:
                return existing
            operation_id = str(request.request_id)
            result = self._new_operation(filename, request)
            _write_operation(self.data_dir, result)
        self._fault("after_operation_record")

        with self._exclusive_restore_context(
            operation_id,
            current_request_tracked=current_request_tracked,
        ):
            if _journal_path(self.data_dir).exists():
                raise RestoreInProgressError("An incomplete restore requires recovery on restart")
            try:
                candidate_manifest = self._validate_candidate(filename, request.expected_sha256)
                pre_restore = self.backup_service._create_backup_locked()
                result = result.model_copy(update={"pre_restore_backup": pre_restore.filename})
                _write_operation(self.data_dir, result)
                self._fault("after_pre_restore_backup")

                token = request.request_id.hex
                staging = self.data_dir / f".pfim-restore-{token}.candidate.db"
                rollback = self.data_dir / f".pfim-restore-{token}.rollback.db"
                staged_sha256 = self._stage_candidate(
                    self.data_dir / filename,
                    staging,
                    request.expected_sha256,
                )
                self._fault("after_candidate_staged")

                result = result.model_copy(update={"state": "committing"})
                _write_operation(self.data_dir, result)
                journal: dict[str, Any] = {
                    "format_version": _JOURNAL_FORMAT_VERSION,
                    "operation_id": operation_id,
                    "phase": "prepared",
                    "database_filename": self.db_path.name,
                    "candidate_filename": filename,
                    "candidate_sha256": candidate_manifest["sha256"],
                    "staging_filename": staging.name,
                    "staged_sha256": staged_sha256,
                    "rollback_filename": rollback.name,
                    "pre_restore_backup": pre_restore.filename,
                    "expected_revision": self.expected_revision,
                    "started_at": result.started_at.isoformat(),
                }
                _atomic_write_json(_journal_path(self.data_dir), journal)
                self._fault("after_journal_prepared")

                self._dispose_engine()
                self._fault("after_engine_dispose")
                self._checkpoint_and_detach_live()
                _validate_database(self.db_path, self.expected_revision)
                journal["rollback_sha256"] = _sha256(self.db_path)
                _atomic_write_json(_journal_path(self.data_dir), journal)
                self._fault("after_sidecars_clean")

                _replace_database_file(
                    self.db_path,
                    rollback,
                    timeout=self.quiesce_timeout,
                )
                _fsync_directory(self.data_dir)
                self._fault("after_live_moved")
                journal["phase"] = "live_moved"
                _atomic_write_json(_journal_path(self.data_dir), journal)
                self._fault("after_journal_live_moved")

                _replace_database_file(
                    staging,
                    self.db_path,
                    timeout=self.quiesce_timeout,
                )
                _fsync_directory(self.data_dir)
                self._fault("after_candidate_installed")
                _validate_database(self.db_path, self.expected_revision)
                if _sha256(self.db_path) != staged_sha256:
                    raise BackupVerificationError(
                        "The installed database hash differs from staging"
                    )
                self._reopen_engine(self.expected_revision)
                self._fault("after_candidate_validated")

                journal["phase"] = "committed"
                _atomic_write_json(_journal_path(self.data_dir), journal)
                self._fault("after_journal_committed")

                result = result.model_copy(
                    update={
                        "state": "completed",
                        "restored": True,
                        "completed_at": _utcnow(),
                        "requires_reload": True,
                        "message": "Restore completed and database reopened",
                    }
                )
                _write_operation(self.data_dir, result)
                _remove_file(rollback)
                self._fault("after_rollback_removed")
                _remove_file(_journal_path(self.data_dir))
                self._fault("after_journal_removed")
                return result
            except Exception as exc:
                try:
                    recovered = _recover_locked(
                        db_path=self.db_path,
                        engine=self.engine,
                        fallback_expected_revision=self.expected_revision,
                    )
                except Exception as recovery_exc:
                    self.gate.poison(operation_id)
                    raise RestoreRecoveryError(
                        "Restore interrupted and automatic rollback failed"
                    ) from recovery_exc
                if recovered is not None and recovered.state == "completed":
                    return recovered
                if isinstance(exc, PFIMError):
                    raise
                raise RestoreFailedError(
                    "Restore cancelled; the previous database has been restored",
                    detail={"operation_id": operation_id},
                ) from exc


def _validated_journal(data_dir: Path, db_path: Path) -> dict[str, Any] | None:
    path = _journal_path(data_dir)
    if not path.is_file():
        return None
    payload = _read_json(path)
    try:
        operation_id = uuid.UUID(str(payload["operation_id"]))
        phase = str(payload["phase"])
        expected_revision = str(payload["expected_revision"])
        candidate_filename = str(payload["candidate_filename"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RestoreRecoveryError("Incomplete restore journal") from exc
    if payload.get("format_version") != _JOURNAL_FORMAT_VERSION or phase not in _PHASES:
        raise RestoreRecoveryError("Unsupported restore journal format or phase")
    if payload.get("database_filename") != db_path.name:
        raise RestoreRecoveryError("The restore journal refers to a different database")
    if not expected_revision or not is_valid_backup_filename(candidate_filename):
        raise RestoreRecoveryError("The restore journal contains an invalid revision or candidate")
    token = operation_id.hex
    if payload.get("staging_filename") != f".pfim-restore-{token}.candidate.db":
        raise RestoreRecoveryError("Invalid staging name in the journal")
    if payload.get("rollback_filename") != f".pfim-restore-{token}.rollback.db":
        raise RestoreRecoveryError("Invalid rollback name in the journal")
    if re.fullmatch(r"[0-9a-f]{64}", str(payload.get("staged_sha256"))) is None:
        raise RestoreRecoveryError("Invalid staging hash in the journal")
    rollback_sha256 = payload.get("rollback_sha256")
    if rollback_sha256 is not None and re.fullmatch(r"[0-9a-f]{64}", str(rollback_sha256)) is None:
        raise RestoreRecoveryError("Invalid rollback hash in the journal")
    if re.fullmatch(r"[0-9a-f]{64}", str(payload.get("candidate_sha256"))) is None:
        raise RestoreRecoveryError("Invalid candidate hash in the journal")
    if not is_valid_backup_filename(str(payload.get("pre_restore_backup"))):
        raise RestoreRecoveryError("Invalid preliminary backup in the journal")
    return payload


def _reconcile_orphan_operations(db_path: Path) -> None:
    data_dir = db_path.parent
    for path in _list_operation_paths(data_dir):
        payload = _read_json(path)
        if payload.get("format_version") != _OPERATION_FORMAT_VERSION:
            raise RestoreRecoveryError(f"Unsupported operation format: {path.name}")
        result = RestoreResult.model_validate(payload)
        if result.state in _TERMINAL_STATES:
            continue
        token = result.operation_id.hex
        staging = data_dir / f".pfim-restore-{token}.candidate.db"
        rollback = data_dir / f".pfim-restore-{token}.rollback.db"
        if rollback.exists():
            raise RestoreRecoveryError(
                "Rollback exists without a journal: automatic recovery is not deterministic"
            )
        _remove_file(staging)
        result = result.model_copy(
            update={
                "state": "failed",
                "restored": False,
                "completed_at": _utcnow(),
                "error_code": "RESTORE_INTERRUPTED_BEFORE_SWAP",
                "message": "Process interrupted before publishing the restore journal",
            }
        )
        _write_operation(data_dir, result)


def _reopen_recovered_engine(engine: Engine, db_path: Path, expected_revision: str) -> None:
    if _engine_database_path(engine) != db_path:
        raise RestoreRecoveryError("The recovery engine does not refer to the journal's database")
    with engine.connect() as connection:
        revisions = tuple(
            row[0]
            for row in connection.execute(
                text("SELECT version_num FROM alembic_version ORDER BY version_num")
            )
        )
    if revisions != (expected_revision,):
        raise RestoreRecoveryError(f"Unexpected engine revision after recovery: {revisions!r}")


def _recover_locked(
    *,
    db_path: Path,
    engine: Engine,
    fallback_expected_revision: str,
) -> RestoreResult | None:
    data_dir = db_path.parent
    journal = _validated_journal(data_dir, db_path)
    if journal is None:
        active_operations: list[RestoreResult] = []
        for path in _list_operation_paths(data_dir):
            payload = _read_json(path)
            if payload.get("format_version") != _OPERATION_FORMAT_VERSION:
                raise RestoreRecoveryError(f"Unsupported operation format: {path.name}")
            result = RestoreResult.model_validate(payload)
            if result.state not in _TERMINAL_STATES:
                active_operations.append(result)
        if active_operations:
            if not db_path.is_file():
                raise RestoreRecoveryError("Database missing with an incomplete restore operation")
            _validate_database(db_path, fallback_expected_revision)
            engine.dispose()
            _reopen_recovered_engine(engine, db_path, fallback_expected_revision)
            _reconcile_orphan_operations(db_path)
        return None

    operation_id = uuid.UUID(str(journal["operation_id"]))
    result = get_restore_operation(data_dir, operation_id)
    expected_revision = str(journal["expected_revision"])
    operation_matches_journal = (
        result.restored_backup == journal["candidate_filename"]
        and result.expected_sha256 == journal["candidate_sha256"]
        and result.pre_restore_backup == journal["pre_restore_backup"]
        and result.alembic_revision == expected_revision
        and result.started_at.isoformat() == journal["started_at"]
    )
    if not operation_matches_journal:
        raise RestoreRecoveryError("The operation record and restore journal do not match")
    phase = str(journal["phase"])
    if phase != "committed" and result.state == "completed":
        raise RestoreRecoveryError("Operation completed before the journal commit")
    if phase == "committed" and result.state in {"failed", "rolled_back"}:
        raise RestoreRecoveryError(
            "Terminal operation state is incompatible with the journal commit"
        )
    staging = data_dir / str(journal["staging_filename"])
    rollback = data_dir / str(journal["rollback_filename"])
    engine.dispose()

    rollback_sha256 = journal.get("rollback_sha256")
    if rollback.is_file():
        if rollback_sha256 is None:
            raise RestoreRecoveryError("Rollback exists without a durable journal hash")
        _validate_database(rollback, expected_revision)
        if _sha256(rollback) != rollback_sha256:
            raise RestoreRecoveryError("The rollback hash differs from the journal")

    try:
        if phase == "committed":
            # After durable commit, the candidate is the only valid outcome. Its absence or corruption
            # requires explicit intervention: silently rolling back would violate the already
            # observable commit point.
            if not db_path.is_file():
                raise RestoreRecoveryError("Committed database is missing")
            _validate_database(db_path, expected_revision)
            if _sha256(db_path) != journal["staged_sha256"]:
                raise RestoreRecoveryError("The live hash differs from the committed candidate")
            _reopen_recovered_engine(engine, db_path, expected_revision)
            result = result.model_copy(
                update={
                    "state": "completed",
                    "restored": True,
                    "completed_at": result.completed_at or _utcnow(),
                    "requires_reload": True,
                    "error_code": None,
                    "message": "Restore committed; recovery completed cleanup",
                }
            )
            _write_operation(data_dir, result)
            _remove_file(rollback)
            _remove_file(staging)
            _remove_file(_journal_path(data_dir))
            return result

        if not rollback.is_file():
            if not db_path.is_file():
                raise RestoreRecoveryError("Pre-restore rollback is unavailable")
            _validate_database(db_path, expected_revision)
            live_sha256 = _sha256(db_path)
            if rollback_sha256 is not None and live_sha256 != rollback_sha256:
                raise RestoreRecoveryError(
                    "Rollback is missing and the live database differs from the pre-restore database"
                )
            if rollback_sha256 is None and phase != "prepared":
                raise RestoreRecoveryError(
                    "The rollback hash is unavailable after moving the live database"
                )
        else:
            if db_path.exists():
                _replace_database_file(db_path, staging, timeout=30.0)
                _fsync_directory(data_dir)
            _replace_database_file(rollback, db_path, timeout=30.0)
            _fsync_directory(data_dir)

        _validate_database(db_path, expected_revision)
        if rollback_sha256 is not None and _sha256(db_path) != rollback_sha256:
            raise RestoreRecoveryError("The live hash after rollback differs from the journal")
        _reopen_recovered_engine(engine, db_path, expected_revision)
        result = result.model_copy(
            update={
                "state": "rolled_back",
                "restored": False,
                "completed_at": _utcnow(),
                "error_code": "RESTORE_ROLLED_BACK",
                "message": "Restore interrupted before commit; the previous database has been restored",
            }
        )
        _write_operation(data_dir, result)
        _remove_file(staging)
        _remove_file(rollback)
        _remove_file(_journal_path(data_dir))
        return result
    except Exception as exc:
        raise RestoreRecoveryError(f"Restore recovery failed for operation {operation_id}") from exc


def recover_pending_restore(
    *,
    db_path: Path,
    engine: Engine,
    expected_revision: str,
    lock_timeout: float = 30.0,
) -> RestoreResult | None:
    """Recover a journal left by a crash before running the startup schema guard."""

    with operation_lock(db_path.parent).hold(timeout=lock_timeout):
        try:
            return _recover_locked(
                db_path=db_path,
                engine=engine,
                fallback_expected_revision=expected_revision,
            )
        except RestoreRecoveryError:
            raise
        except Exception as exc:
            raise RestoreRecoveryError("Restore recovery failed with access blocked") from exc
