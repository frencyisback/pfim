"""Router: prices."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.repositories.price_repo import PriceRepository
from app.schemas.price import PriceCreate, PriceImportPreviewResult, PriceImportResult, PriceRead
from app.services.import_service import ImportService
from app.utils.errors import NotFoundError
from app.utils.upload import read_csv_upload

router = APIRouter(prefix="/prices", tags=["prices"])


@router.post("", response_model=PriceRead, status_code=201)
def add_price(payload: PriceCreate, db: Session = Depends(get_db, scope="function")):
    return ImportService(db).add_price(payload)


@router.post("/import/preview", response_model=PriceImportPreviewResult)
async def preview_import_prices(
    file: UploadFile = File(...),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db, scope="function"),
):
    content = await read_csv_upload(file)
    return ImportService(db).preview_prices(content, page=page, page_size=page_size)


@router.post("/import", response_model=PriceImportResult)
async def import_prices(
    file: UploadFile = File(...), db: Session = Depends(get_db, scope="function")
):
    content = await read_csv_upload(file)
    return ImportService(db).import_prices(content)


@router.get("/latest", response_model=list[PriceRead])
def get_all_latest_prices(db: Session = Depends(get_db, scope="function")):
    """Return the latest non-future price for every security in one request. Register this static
    route before /{security_id} so FastAPI does not parse latest as an integer.
    """
    latest = PriceRepository(db).latest_by_security(as_of=dt.date.today())
    return [latest[security_id] for security_id in sorted(latest)]


@router.get("/{security_id}", response_model=list[PriceRead])
def get_price_history(security_id: int, db: Session = Depends(get_db, scope="function")):
    return PriceRepository(db).list_for_security(security_id)


@router.get("/{security_id}/latest", response_model=PriceRead)
def get_latest_price(security_id: int, db: Session = Depends(get_db, scope="function")):
    price = PriceRepository(db).get_latest(security_id, as_of=dt.date.today())
    if price is None:
        raise NotFoundError(
            f"No price is available for security {security_id}",
            detail={"security_id": security_id},
        )
    return price
