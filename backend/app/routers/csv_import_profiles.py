"""Router: csv-import-profiles."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.csv_import_profile import CsvImportProfileCreate, CsvImportProfileRead
from app.services.csv_import_profile_service import CsvImportProfileService

router = APIRouter(prefix="/csv-import-profiles", tags=["csv-import-profiles"])


@router.get("", response_model=list[CsvImportProfileRead])
def list_csv_import_profiles(db: Session = Depends(get_db, scope="function")):
    return CsvImportProfileService(db).list_profiles()


@router.post("", response_model=CsvImportProfileRead, status_code=201)
def create_csv_import_profile(
    payload: CsvImportProfileCreate, db: Session = Depends(get_db, scope="function")
):
    return CsvImportProfileService(db).create_profile(payload)


@router.delete("/{id}", status_code=204)
def delete_csv_import_profile(id: int, db: Session = Depends(get_db, scope="function")):
    CsvImportProfileService(db).delete_profile(id)
