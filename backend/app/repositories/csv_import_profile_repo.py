"""Repository: CsvImportProfileRepository."""

from __future__ import annotations

from sqlalchemy import func, select

from app.models.csv_import_profile import CsvImportProfile
from app.repositories.base import BaseRepository


class CsvImportProfileRepository(BaseRepository[CsvImportProfile]):
    model = CsvImportProfile

    def get_by_name(self, name: str) -> CsvImportProfile | None:
        return self.db.scalars(
            select(CsvImportProfile).where(func.lower(CsvImportProfile.name) == name.lower())
        ).first()

    def list(self) -> list[CsvImportProfile]:
        return list(self.db.scalars(select(CsvImportProfile).order_by(CsvImportProfile.name)))
