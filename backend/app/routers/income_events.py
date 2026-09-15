"""Router: income-events."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.income_event import IncomeEventCreate, IncomeEventRead, IncomeEventsSummary
from app.services.income_event_service import IncomeEventService

router = APIRouter(prefix="/income-events", tags=["income-events"])


@router.get("", response_model=list[IncomeEventRead])
def list_income_events(
    security_id: int | None = Query(default=None),
    date_from: dt.date | None = Query(default=None),
    date_to: dt.date | None = Query(default=None),
    db: Session = Depends(get_db, scope="function"),
):
    return IncomeEventService(db).list_events(
        security_id=security_id, date_from=date_from, date_to=date_to
    )


@router.post("", response_model=IncomeEventRead, status_code=201)
def create_income_event(
    payload: IncomeEventCreate, db: Session = Depends(get_db, scope="function")
):
    return IncomeEventService(db).create_event(payload)


@router.delete("/{id}", status_code=204)
def delete_income_event(id: int, db: Session = Depends(get_db, scope="function")):
    IncomeEventService(db).delete_event(id)


@router.get("/summary", response_model=IncomeEventsSummary)
def income_events_summary(
    date_from: dt.date | None = Query(default=None),
    date_to: dt.date | None = Query(default=None),
    db: Session = Depends(get_db, scope="function"),
):
    return IncomeEventService(db).get_summary(date_from=date_from, date_to=date_to)
