"""Router: portfolio."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.portfolio import PortfolioSummary, PositionRead
from app.services.portfolio_service import PortfolioService

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("", response_model=list[PositionRead])
def get_portfolio_positions(db: Session = Depends(get_db, scope="function")):
    return PortfolioService(db).get_all_positions()


@router.get("/summary", response_model=PortfolioSummary)
def get_portfolio_summary(db: Session = Depends(get_db, scope="function")):
    return PortfolioService(db).get_summary()


@router.get("/{security_id}", response_model=PositionRead)
def get_portfolio_position_detail(
    security_id: int, db: Session = Depends(get_db, scope="function")
):
    return PortfolioService(db).get_position(security_id)
