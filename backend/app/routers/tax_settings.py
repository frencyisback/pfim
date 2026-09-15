"""Router: tax-settings."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.tax_settings import TaxSettingRead, TaxSettingUpdate
from app.services.tax_settings_service import TaxSettingsService

router = APIRouter(prefix="/tax-settings", tags=["tax-settings"])


@router.get("", response_model=list[TaxSettingRead])
def list_tax_settings(db: Session = Depends(get_db, scope="function")):
    return TaxSettingsService(db).list_settings()


@router.put("/{key}", response_model=TaxSettingRead)
def update_tax_setting(
    key: str, payload: TaxSettingUpdate, db: Session = Depends(get_db, scope="function")
):
    return TaxSettingsService(db).update_setting(key, payload.value)
