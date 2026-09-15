"""Transactions router. Import preview uses POST to receive a CSV file in the request body;
multipart GET bodies are not standard.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.common import PaginatedResponse
from app.schemas.transaction import (
    ImportPreviewResult,
    ImportResult,
    TransactionCreate,
    TransactionRead,
    TransactionSummary,
    TransferCreate,
    TransferResult,
)
from app.services.transaction_service import TransactionService
from app.utils.csv_parser import CsvProfile
from app.utils.upload import read_csv_upload

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("", response_model=PaginatedResponse[TransactionRead])
def list_transactions(
    account_id: int | None = Query(default=None),
    category_id: int | None = Query(default=None),
    date_from: dt.date | None = Query(default=None),
    date_to: dt.date | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    sort_by: str = Query(
        default="date", pattern="^(date|account_id|category_id|description|amount)$"
    ),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db, scope="function"),
):
    service = TransactionService(db)
    items, total = service.list_transactions(
        account_id=account_id,
        category_id=category_id,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    return PaginatedResponse(
        items=[service.to_read_dict(t) for t in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/summary", response_model=TransactionSummary)
def transactions_summary(
    date_from: dt.date | None = Query(default=None),
    date_to: dt.date | None = Query(default=None),
    db: Session = Depends(get_db, scope="function"),
):
    return TransactionService(db).get_summary(date_from=date_from, date_to=date_to)


@router.get("/{id}", response_model=TransactionRead)
def get_transaction(id: int, db: Session = Depends(get_db, scope="function")):
    service = TransactionService(db)
    return service.to_read_dict(service.get_transaction(id))


@router.post("", response_model=TransactionRead, status_code=201)
def create_transaction(payload: TransactionCreate, db: Session = Depends(get_db, scope="function")):
    service = TransactionService(db)
    return service.to_read_dict(service.create_transaction(payload))


@router.post("/transfer", response_model=TransferResult, status_code=201)
def create_transfer(payload: TransferCreate, db: Session = Depends(get_db, scope="function")):
    """Transfer between the user's own accounts by creating two linked transactions."""
    service = TransactionService(db)
    tx_from, tx_to = service.create_transfer(payload)
    return TransferResult(
        from_transaction=service.to_read_dict(tx_from),
        to_transaction=service.to_read_dict(tx_to),
    )


@router.delete("/{id}", status_code=204)
def delete_transaction(id: int, db: Session = Depends(get_db, scope="function")):
    TransactionService(db).delete_transaction(id)


def _build_profile(
    delimiter: str,
    skip_rows: int,
    date_format: str,
    date_column: str,
    description_column: str,
    amount_column: str,
    decimal_separator: str,
    default_currency: str,
    category_column: str,
) -> CsvProfile:
    return CsvProfile(
        delimiter=delimiter,
        skip_rows=skip_rows,
        date_format=date_format,
        date_column=date_column,
        description_column=description_column,
        amount_column=amount_column,
        category_column=category_column,
        decimal_separator=decimal_separator,
        default_currency=default_currency,
    )


@router.post("/import/preview", response_model=ImportPreviewResult)
async def preview_import_transactions(
    file: UploadFile = File(...),
    account_id: int = Form(
        ...,
        description="Destination account, also passed to the import. "
        "Required to detect duplicates: the same row can be a duplicate "
        "on one account and a new movement on another.",
    ),
    delimiter: str = Form(default=",", min_length=1, max_length=1),
    skip_rows: int = Form(default=0, ge=0),
    date_format: str = Form(default="%Y-%m-%d"),
    date_column: str = Form(default="date"),
    description_column: str = Form(default="description"),
    amount_column: str = Form(default="amount"),
    category_column: str = Form(...),
    decimal_separator: str = Form(default=".", min_length=1, max_length=1),
    default_currency: str = Form(default="EUR", min_length=3, max_length=3),
    fx_rate: Decimal | None = Form(
        default=None,
        gt=0,
        description="Exchange rate applied to every row in the file. Required when "
        "default_currency is not EUR: a bank statement uses a single "
        "currency.",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db, scope="function"),
):
    content = await read_csv_upload(file)
    profile = _build_profile(
        delimiter,
        skip_rows,
        date_format,
        date_column,
        description_column,
        amount_column,
        decimal_separator,
        default_currency,
        category_column,
    )
    return TransactionService(db).preview_import(
        content,
        profile,
        account_id=account_id,
        fx_rate=fx_rate,
        page=page,
        page_size=page_size,
    )


@router.post("/import", response_model=ImportResult)
async def import_transactions(
    file: UploadFile = File(...),
    account_id: int = Form(...),
    delimiter: str = Form(default=",", min_length=1, max_length=1),
    skip_rows: int = Form(default=0, ge=0),
    date_format: str = Form(default="%Y-%m-%d"),
    date_column: str = Form(default="date"),
    description_column: str = Form(default="description"),
    amount_column: str = Form(default="amount"),
    category_column: str = Form(...),
    decimal_separator: str = Form(default=".", min_length=1, max_length=1),
    default_currency: str = Form(default="EUR", min_length=3, max_length=3),
    fx_rate: Decimal | None = Form(
        default=None,
        gt=0,
        description="Exchange rate applied to every row in the file. Required when "
        "default_currency is not EUR.",
    ),
    db: Session = Depends(get_db, scope="function"),
):
    content = await read_csv_upload(file)
    profile = _build_profile(
        delimiter,
        skip_rows,
        date_format,
        date_column,
        description_column,
        amount_column,
        decimal_separator,
        default_currency,
        category_column,
    )
    return TransactionService(db).import_transactions(
        content,
        profile,
        account_id=account_id,
        import_source=file.filename or "csv_import",
        fx_rate=fx_rate,
    )
