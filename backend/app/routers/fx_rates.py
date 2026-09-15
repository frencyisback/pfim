"""Router: fx-rates."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.repositories.fx_rate_repo import FxRateRepository
from app.schemas.fx_rate import FxRateImportResult, FxRateRead, FxRateSuggestion
from app.services.import_service import ImportService
from app.utils.errors import NotFoundError
from app.utils.upload import read_csv_upload

router = APIRouter(prefix="/fx-rates", tags=["fx-rates"])


@router.post("/import", response_model=FxRateImportResult)
async def import_fx_rates(
    file: UploadFile = File(...), db: Session = Depends(get_db, scope="function")
):
    content = await read_csv_upload(file)
    return ImportService(db).import_fx_rates(content)


@router.get("", response_model=list[FxRateRead])
def list_fx_rates(db: Session = Depends(get_db, scope="function")):
    return FxRateRepository(db).list()


@router.get("/suggest", response_model=FxRateSuggestion)
def suggest_fx_rate(
    currency: str,
    date: dt.date,
    db: Session = Depends(get_db, scope="function"),
):
    """Suggest the latest stored exchange rate on or before date. The rate confirmed by the user
    at save time is authoritative and frozen on the record. EUR always returns 1 without a
    lookup. A missing stored rate returns rate: null so the user can enter it manually.
    """
    code = currency.strip().upper()
    if code == "EUR":
        return FxRateSuggestion(currency=code, date=date, rate=Decimal("1"), source="fixed")
    rate = FxRateRepository(db).get_as_of(code, "EUR", date)
    if rate is None:
        return FxRateSuggestion(currency=code, date=date, rate=None, source=None)
    return FxRateSuggestion(
        currency=code, date=date, rate=rate.rate, rate_date=rate.date, source=rate.source
    )


@router.get("/{from_ccy}/{to_ccy}/{date}", response_model=FxRateRead)
def get_fx_rate(
    from_ccy: str, to_ccy: str, date: dt.date, db: Session = Depends(get_db, scope="function")
):
    rate = FxRateRepository(db).get(from_ccy.upper(), to_ccy.upper(), date)
    if rate is None:
        raise NotFoundError(
            f"No exchange rate found for {from_ccy}->{to_ccy} on {date}",
            detail={"from": from_ccy, "to": to_ccy, "date": str(date)},
        )
    return rate
