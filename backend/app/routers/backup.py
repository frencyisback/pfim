"""Router: backup."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.schemas.backup import BackupInfo, BackupStatus, RestoreRequest, RestoreResult
from app.services.backup_service import BackupService, is_valid_backup_filename
from app.services.restore_service import get_restore_operation
from app.utils.errors import ValidationErrorPFIM

router = APIRouter(prefix="/backup", tags=["backup"])


@router.post("", response_model=BackupInfo, status_code=201)
def create_backup() -> BackupInfo:
    return BackupService().create_backup()


@router.get("", response_model=list[BackupInfo])
def list_backups() -> list[BackupInfo]:
    return BackupService().list_backups()


@router.get("/status", response_model=BackupStatus)
def backup_status() -> BackupStatus:
    return BackupService().status()


@router.get("/restore-operations/{operation_id}", response_model=RestoreResult)
def restore_operation_status(operation_id: uuid.UUID) -> RestoreResult:
    service = BackupService()
    return get_restore_operation(service.data_dir, operation_id)


@router.get("/{filename}/download")
def download_backup(filename: str):
    """Download the backup for copying elsewhere, such as external cloud storage."""
    if not is_valid_backup_filename(filename):
        raise ValidationErrorPFIM("Invalid filename", detail={"filename": filename})
    service = BackupService()
    path = service.get_backup_path(filename)
    return FileResponse(
        path,
        filename=filename,
        media_type="application/octet-stream",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/{filename}/manifest")
def download_backup_manifest(filename: str):
    """Download the verified manifest to keep alongside the SQLite file."""

    service = BackupService()
    path = service.get_manifest_path(filename)
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/{filename}/restore", response_model=RestoreResult)
def restore_backup(filename: str, request: RestoreRequest) -> RestoreResult:
    return BackupService().restore_backup(filename, request)
