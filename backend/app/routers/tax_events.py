"""Router: tax-events."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.tax_event import TaxEventCreate, TaxEventRead, TaxEventUpdate
from app.services.tax_service import TaxService

router = APIRouter(prefix="/tax-events", tags=["tax-events"])


@router.get("", response_model=list[TaxEventRead])
def list_tax_events(
    date_from: dt.date | None = Query(default=None),
    date_to: dt.date | None = Query(default=None),
    db: Session = Depends(get_db, scope="function"),
):
    return TaxService(db).list_events(date_from=date_from, date_to=date_to)


@router.post("", response_model=TaxEventRead, status_code=201)
def create_tax_event(payload: TaxEventCreate, db: Session = Depends(get_db, scope="function")):
    """Record a manual tax event. A trade or income reference does not transfer ownership to the
    synchronizer. Automatic events are created exclusively through the sale workflow.
    """
    return TaxService(db).create_event(payload)


@router.put("/{id}", response_model=TaxEventRead)
def update_tax_event(
    id: int, payload: TaxEventUpdate, db: Session = Depends(get_db, scope="function")
):
    return TaxService(db).update_event(id, payload)


@router.delete("/{id}", status_code=204)
def delete_tax_event(id: int, db: Session = Depends(get_db, scope="function")):
    TaxService(db).delete_event(id)
