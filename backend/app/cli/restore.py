"""Crash-safe offline restore, available only while the backend is stopped."""

from __future__ import annotations

import argparse
import sys
import uuid

from app.config import settings
from app.database import engine
from app.maintenance import backend_instance_lock
from app.schema_guard import ensure_database_schema_current
from app.schemas.backup import RestoreRequest
from app.services.backup_service import BackupService
from app.services.restore_service import RestoreService, recover_pending_restore
from app.utils.errors import PFIMError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Restore a verified PFIM backup with a crash-safe protocol"
    )
    parser.add_argument("filename")
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--confirmation", required=True)
    parser.add_argument("--request-id", type=uuid.UUID, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    service = BackupService()
    operation_id = args.request_id or uuid.uuid4()
    request = RestoreRequest(
        request_id=operation_id,
        expected_sha256=args.expected_sha256,
        confirmation=args.confirmation,
    )
    instance = backend_instance_lock(service.data_dir)
    try:
        with instance.hold(timeout=0):
            recover_pending_restore(
                db_path=service.db_path,
                engine=engine,
                expected_revision=service.expected_revision,
                lock_timeout=float(settings.restore_quiesce_timeout_seconds),
            )
            ensure_database_schema_current(engine)
            result = RestoreService(backup_service=service, engine=engine).restore_backup(
                args.filename,
                request,
                current_request_tracked=False,
            )
    except PFIMError as exc:
        print(
            f"{exc.error_code}: {exc.message} (operation_id={operation_id})",
            file=sys.stderr,
        )
        return 1
    finally:
        engine.dispose()
    print(result.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
