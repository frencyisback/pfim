"""Service: CategoryService."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.category import Category
from app.models.transaction import Transaction
from app.repositories.category_repo import CategoryRepository
from app.schemas.category import CategoryCreate
from app.utils.errors import ConflictError, NotFoundError, ValidationErrorPFIM


class CategoryService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = CategoryRepository(db)

    def list_categories(self) -> list[Category]:
        return self.repo.list()

    def get_category(self, category_id: int) -> Category:
        category = self.repo.get(category_id)
        if category is None:
            raise NotFoundError(
                f"Category {category_id} not found",
                detail={"category_id": category_id},
            )
        return category

    def _validate_parent(self, parent_id: int | None, child_type: str) -> None:
        """Limit the category hierarchy to two levels: a parent cannot itself have a parent.
        Child categories must have the same income/expense/transfer type as their parent.
        """
        if parent_id is None:
            return
        parent = self.repo.get(parent_id)
        if parent is None:
            raise ValidationErrorPFIM(
                f"Parent category {parent_id} not found",
                detail={"parent_id": parent_id},
            )
        if parent.parent_id is not None:
            raise ValidationErrorPFIM(
                "Category hierarchies support at most 2 levels",
                detail={"parent_id": parent_id},
            )
        usage_count = self.db.scalar(
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.category_id == parent_id)
        )
        if usage_count:
            raise ConflictError(
                "Cannot create a subcategory: the parent category is already used "
                "by transactions and would cease to be an assignable leaf",
                detail={
                    "parent_id": parent_id,
                    "transactions_count": usage_count,
                },
            )
        if parent.type != child_type:
            raise ValidationErrorPFIM(
                f"A subcategory of type '{child_type}' cannot have a parent "
                f"category of type '{parent.type}'",
                detail={
                    "parent_id": parent_id,
                    "parent_type": parent.type,
                    "child_type": child_type,
                },
            )

    def create_category(self, data: CategoryCreate) -> Category:
        self._validate_parent(data.parent_id, data.type)
        existing = self.repo.get_by_name(data.name)
        if existing is not None:
            raise ConflictError(
                f"Category '{data.name}' already exists",
                detail={"name": data.name, "category_ids": [existing.id]},
            )
        category = Category(**data.model_dump(), is_system=False)
        return self.repo.add(category)

    def delete_category(self, category_id: int) -> None:
        """Allow deletion of system categories too. Block deletion while a category has children
        or is used by transactions; those must first be reassigned or deleted.
        """
        category = self.get_category(category_id)
        if category.children:
            raise ConflictError(
                "Cannot delete a category with subcategories",
                detail={"category_id": category_id, "children_count": len(category.children)},
            )
        usage_count = self.db.scalar(
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.category_id == category_id)
        )
        if usage_count:
            raise ConflictError(
                f"Cannot delete: {usage_count} transactions use this category",
                detail={"category_id": category_id, "transactions_count": usage_count},
            )
        self.repo.delete(category_id)
