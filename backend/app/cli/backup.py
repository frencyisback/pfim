"""Safe entry point for make backup and scripts/backup.ps1. Delegate to the API's backup service
to use SQLite Online Backup API, verification, hashing, and manifests instead of copying the
live file directly.
"""

from __future__ import annotations

import sys

from app.services.backup_service import BackupService
from app.utils.errors import PFIMError


def main() -> int:
    try:
        result = BackupService().create_backup()
    except PFIMError as exc:
        print(f"{exc.error_code}: {exc.message}", file=sys.stderr)
        return 1
    print(result.model_dump_json())
    return 0


if __name__ == "__main__":  # pragma: no branch - standard CLI entry point
    raise SystemExit(main())
