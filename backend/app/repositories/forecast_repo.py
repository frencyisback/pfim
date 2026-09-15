"""Repository: ForecastRepository."""

from __future__ import annotations

from sqlalchemy import select

from app.models.forecast_scenario import ForecastScenario
from app.repositories.base import BaseRepository


class ForecastRepository(BaseRepository[ForecastScenario]):
    model = ForecastScenario

    def list(self) -> list[ForecastScenario]:
        return list(
            self.db.scalars(select(ForecastScenario).order_by(ForecastScenario.created_at.desc()))
        )
