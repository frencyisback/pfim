"""Router: performance."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.performance import PerformanceMetrics, PortfolioPerformance
from app.services.performance_service import PerformanceService

router = APIRouter(prefix="/performance", tags=["performance"])


@router.get("/portfolio", response_model=PortfolioPerformance)
def portfolio_performance(
    income_basis: Literal["net", "gross"] | None = Query(default=None),
    cost_basis: Literal["exclude", "include"] | None = Query(default=None),
    gross: bool | None = Query(
        default=None,
        deprecated=True,
        description="Deprecated alias: true means income_basis=gross, false means net.",
    ),
    db: Session = Depends(get_db, scope="function"),
):
    return PerformanceService(db).portfolio_performance(
        income_basis=income_basis, cost_basis=cost_basis, gross=gross
    )


@router.get("/{security_id}", response_model=PerformanceMetrics)
def security_performance(
    security_id: int,
    income_basis: Literal["net", "gross"] | None = Query(default=None),
    cost_basis: Literal["exclude", "include"] | None = Query(default=None),
    gross: bool | None = Query(
        default=None,
        deprecated=True,
        description="Deprecated alias: true means income_basis=gross, false means net.",
    ),
    db: Session = Depends(get_db, scope="function"),
):
    return PerformanceService(db).security_performance(
        security_id, income_basis=income_basis, cost_basis=cost_basis, gross=gross
    )
