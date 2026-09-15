"""Router: forecasts."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.forecast import (
    ForecastCompareRequest,
    ForecastCompareResult,
    ForecastRunResult,
    ForecastScenarioCreate,
    ForecastScenarioRead,
)
from app.services.forecast_service import ForecastService

router = APIRouter(prefix="/forecasts", tags=["forecasts"])


@router.post("/scenarios", response_model=ForecastScenarioRead, status_code=201)
def create_forecast_scenario(
    payload: ForecastScenarioCreate, db: Session = Depends(get_db, scope="function")
):
    service = ForecastService(db)
    return service.to_read_dict(service.create_scenario(payload))


@router.get("/scenarios", response_model=list[ForecastScenarioRead])
def list_forecast_scenarios(db: Session = Depends(get_db, scope="function")):
    service = ForecastService(db)
    return [service.to_read_dict(s) for s in service.list_scenarios()]


@router.get("/scenarios/{id}", response_model=ForecastScenarioRead)
def get_forecast_scenario(id: int, db: Session = Depends(get_db, scope="function")):
    service = ForecastService(db)
    return service.to_read_dict(service.get_scenario(id))


@router.delete("/scenarios/{id}", status_code=204)
def delete_forecast_scenario(id: int, db: Session = Depends(get_db, scope="function")):
    ForecastService(db).delete_scenario(id)


@router.post("/run/{id}", response_model=ForecastRunResult)
def run_forecast(id: int, db: Session = Depends(get_db, scope="function")):
    return ForecastService(db).run_scenario(id)


@router.post("/compare", response_model=ForecastCompareResult)
def compare_forecasts(
    payload: ForecastCompareRequest, db: Session = Depends(get_db, scope="function")
):
    results = ForecastService(db).compare_scenarios(payload.scenario_ids)
    return ForecastCompareResult(results=results)
