"""Service: CsvImportProfileService."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.csv_import_profile import CsvImportProfile
from app.repositories.csv_import_profile_repo import CsvImportProfileRepository
from app.schemas.csv_import_profile import CsvImportProfileCreate
from app.utils.errors import ConflictError, NotFoundError


class CsvImportProfileService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = CsvImportProfileRepository(db)

    def list_profiles(self) -> list[CsvImportProfile]:
        return self.repo.list()

    def get_profile(self, profile_id: int) -> CsvImportProfile:
        profile = self.repo.get(profile_id)
        if profile is None:
            raise NotFoundError(
                f"CSV profile {profile_id} not found", detail={"profile_id": profile_id}
            )
        return profile

    def create_profile(self, data: CsvImportProfileCreate) -> CsvImportProfile:
        if self.repo.get_by_name(data.name) is not None:
            raise ConflictError(
                f"CSV profile '{data.name}' already exists", detail={"name": data.name}
            )
        profile = CsvImportProfile(**data.model_dump())
        return self.repo.add(profile)

    def delete_profile(self, profile_id: int) -> None:
        self.get_profile(profile_id)
        self.repo.delete(profile_id)
