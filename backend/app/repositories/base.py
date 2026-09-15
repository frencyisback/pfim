"""Common repository operations: primary-key lookup, insertion, update, and deletion.
FxRateRepository uses a date/source/target currency key, TaxSettingRepository only provides
upsert on a text key, and PriceRepository upserts by security/date; these repositories
therefore have separate interfaces.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from sqlalchemy.orm import Session

from app.database import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """Primary-key CRUD. Use flush(), never commit(): app.database.get_db commits once per
    request to keep composite operations atomic. Refresh exposes database-generated IDs and
    values before commit. Subclasses set model and provide their entity-specific queries.
    """

    model: type[ModelT]

    def __init__(self, db: Session):
        self.db = db

    def get(self, id_) -> ModelT | None:
        return self.db.get(self.model, id_)

    def add(self, entity: ModelT) -> ModelT:
        self.db.add(entity)
        self.db.flush()
        self.db.refresh(entity)
        return entity

    def update(self, entity: ModelT) -> ModelT:
        self.db.flush()
        self.db.refresh(entity)
        return entity

    def delete(self, id_) -> None:
        entity = self.get(id_)
        if entity:
            self.db.delete(entity)
            self.db.flush()
