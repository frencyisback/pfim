"""Router: securities."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.security import SecurityCreate, SecurityRead, SecurityUpdate
from app.services.security_service import SecurityService

router = APIRouter(prefix="/securities", tags=["securities"])


@router.get("", response_model=list[SecurityRead])
def list_securities(
    only_active: bool = Query(default=False), db: Session = Depends(get_db, scope="function")
):
    return SecurityService(db).list_securities(only_active=only_active)


@router.post("", response_model=SecurityRead, status_code=201)
def create_security(payload: SecurityCreate, db: Session = Depends(get_db, scope="function")):
    return SecurityService(db).create_security(payload)


@router.put("/{id}", response_model=SecurityRead)
def update_security(
    id: int, payload: SecurityUpdate, db: Session = Depends(get_db, scope="function")
):
    return SecurityService(db).update_security(id, payload)


@router.delete("/{id}", status_code=204)
def delete_security(id: int, db: Session = Depends(get_db, scope="function")):
    SecurityService(db).delete_security(id)
