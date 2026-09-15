"""Router: categories."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.category import CategoryCreate, CategoryRead
from app.services.category_service import CategoryService

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("", response_model=list[CategoryRead])
def list_categories(db: Session = Depends(get_db, scope="function")):
    return CategoryService(db).list_categories()


@router.post("", response_model=CategoryRead, status_code=201)
def create_category(payload: CategoryCreate, db: Session = Depends(get_db, scope="function")):
    return CategoryService(db).create_category(payload)


@router.delete("/{id}", status_code=204)
def delete_category(id: int, db: Session = Depends(get_db, scope="function")):
    CategoryService(db).delete_category(id)
