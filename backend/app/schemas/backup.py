"""Pydantic schemas: backup/restore."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, Field


class BackupInfo(BaseModel):
    filename: str
    size_bytes: int
    created_at: dt.datetime
    verified: bool = False
    verification_error: str | None = None
    sha256: str | None = None
    alembic_revision: str | None = None
    manifest_filename: str | None = None
    restore_eligible: bool = False
    restore_ineligible_reason: str | None = None


class BackupStatus(BaseModel):
    backup_enabled: bool
    restore_enabled: bool
    expected_alembic_revision: str
    maintenance_mode: bool = False
    restore_state: str = "idle"
    active_restore_id: str | None = None


class RestoreRequest(BaseModel):
    request_id: uuid.UUID
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmation: str = Field(min_length=1, max_length=300)


RestoreState = Literal[
    "preparing",
    "committing",
    "recovering",
    "completed",
    "rolled_back",
    "failed",
]


class RestoreResult(BaseModel):
    operation_id: uuid.UUID
    state: RestoreState
    restored: bool
    restored_backup: str
    expected_sha256: str
    pre_restore_backup: str | None
    alembic_revision: str
    started_at: dt.datetime
    completed_at: dt.datetime | None = None
    requires_reload: bool = False
    error_code: str | None = None
    message: str | None = None
