"""Router: portfolio_costs."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.portfolio_cost import PortfolioCostCreate, PortfolioCostRead
from app.services.portfolio_cost_service import PortfolioCostService

router = APIRouter(prefix="/portfolio-costs", tags=["portfolio-costs"])


@router.get("", response_model=list[PortfolioCostRead])
def list_portfolio_costs(
    account_id: int | None = Query(default=None),
    date_from: dt.date | None = Query(default=None),
    date_to: dt.date | None = Query(default=None),
    db: Session = Depends(get_db, scope="function"),
):
    return PortfolioCostService(db).list_costs(
        account_id=account_id, date_from=date_from, date_to=date_to
    )


@router.post("", response_model=PortfolioCostRead, status_code=201)
def create_portfolio_cost(
    payload: PortfolioCostCreate, db: Session = Depends(get_db, scope="function")
):
    return PortfolioCostService(db).create_cost(payload)


@router.delete("/{id}", status_code=204)
def delete_portfolio_cost(id: int, db: Session = Depends(get_db, scope="function")):
    PortfolioCostService(db).delete_cost(id)
