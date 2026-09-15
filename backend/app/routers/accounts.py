"""Router: accounts."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.account import (
    AccountBalance,
    AccountBalanceHistoryPoint,
    AccountCreate,
    AccountRead,
    AccountUpdate,
)
from app.services.account_service import AccountService

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("", response_model=list[AccountRead])
def list_accounts(
    only_active: bool = Query(default=False),
    db: Session = Depends(get_db, scope="function"),
):
    return AccountService(db).list_accounts(only_active=only_active)


@router.post("", response_model=AccountRead, status_code=201)
def create_account(payload: AccountCreate, db: Session = Depends(get_db, scope="function")):
    return AccountService(db).create_account(payload)


@router.put("/{id}", response_model=AccountRead)
def update_account(
    id: int, payload: AccountUpdate, db: Session = Depends(get_db, scope="function")
):
    return AccountService(db).update_account(id, payload)


@router.post("/{id}/deactivate", response_model=AccountRead)
def deactivate_account(id: int, db: Session = Depends(get_db, scope="function")):
    """Soft-delete an account while preserving its history."""
    return AccountService(db).deactivate_account(id)


@router.delete("/{id}", status_code=204)
def delete_account(id: int, db: Session = Depends(get_db, scope="function")):
    """Permanently delete an account unless transactions or trades reference it."""
    AccountService(db).delete_account(id)


@router.get("/{id}/balance", response_model=AccountBalance)
def get_account_balance(
    id: int,
    as_of_date: dt.date | None = Query(default=None),
    db: Session = Depends(get_db, scope="function"),
):
    return AccountService(db).get_balance(id, as_of_date=as_of_date)


@router.get("/{id}/history", response_model=list[AccountBalanceHistoryPoint])
def get_account_history(id: int, db: Session = Depends(get_db, scope="function")):
    """Balance history with one point for each date containing movements."""
    return AccountService(db).get_balance_history(id)
