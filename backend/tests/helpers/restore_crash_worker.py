"""Worker forcibly terminated by the restore protocol tests."""

from __future__ import annotations

import argparse
import os
import uuid
from pathlib import Path

from sqlalchemy import create_engine

from app.maintenance import MaintenanceGate
from app.schemas.backup import RestoreRequest
from app.services.backup_service import BackupService
from app.services.restore_service import RestoreService


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("db_path", type=Path)
    parser.add_argument("filename")
    parser.add_argument("sha256")
    parser.add_argument("request_id", type=uuid.UUID)
    parser.add_argument("revision")
    parser.add_argument("fault_point")
    args = parser.parse_args()

    target_engine = create_engine(f"sqlite:///{args.db_path}")
    backup_service = BackupService(
        db_path=args.db_path,
        backup_enabled=True,
        expected_revision=args.revision,
    )

    def hard_crash(point: str) -> None:
        if point == args.fault_point:
            os._exit(86)

    request = RestoreRequest(
        request_id=args.request_id,
        expected_sha256=args.sha256,
        confirmation=f"RESTORE {args.filename}",
    )
    RestoreService(
        backup_service=backup_service,
        engine=target_engine,
        gate=MaintenanceGate(),
        restore_enabled=True,
        quiesce_timeout=5,
        fault_hook=hard_crash,
    ).restore_backup(args.filename, request, current_request_tracked=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
