"""Pydantic schemas: Account."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.utils.numeric_limits import normalize_numeric_18_6


def _is_nonzero_persistible_opening_balance(value: Decimal) -> bool:
    """Leave accounting representability errors to the service. The schema rejects ordinary
    investment-account cash conflicts immediately, but underflow, overflow, and non-finite
    values must reach the service's uniform structured error handling.
    """
    try:
        return normalize_numeric_18_6(value, label="The opening balance") != 0
    except ValueError:
        return False


class AccountBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    type: str = Field(..., pattern="^(checking|savings|investment|cash)$")
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    # Allow nonfinite values through the schema so the service can return the same
    # application-level 400 error used for underflow and overflow. Nothing reaches the ORM
    # before that guard.
    opening_balance: Decimal = Field(default=Decimal("0"), allow_inf_nan=True)
    notes: str | None = None
    reference_account_id: int | None = None


class AccountCreate(AccountBase):
    opened_on: dt.date | None = None

    @model_validator(mode="after")
    def _validate_creation_invariants(self):
        # The service also enforces this rule when a partial update does not contain both type and
        # balance.
        if self.type == "investment" and _is_nonzero_persistible_opening_balance(
            self.opening_balance
        ):
            raise ValueError(
                "an investment account must have a zero opening balance; "
                "cash belongs to the reference account"
            )
        if self.opened_on is not None and self.opened_on > dt.date.today():
            raise ValueError("the account opening date cannot be in the future")
        return self


class AccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    type: str | None = Field(default=None, pattern="^(checking|savings|investment|cash)$")
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    opening_balance: Decimal | None = Field(default=None, allow_inf_nan=True)
    notes: str | None = None
    is_active: bool | None = None
    reference_account_id: int | None = None

    @model_validator(mode="after")
    def _required_columns_cannot_be_explicit_null(self):
        """Distinguish omitted fields from explicit null in partial updates. None defaults
        represent absent fields, while the corresponding columns are non-nullable. Reject
        explicit null before Decimal conversion or commit can produce HTTP 500. Notes and
        reference account can intentionally be cleared.
        """
        non_nullable_fields = {
            "name",
            "type",
            "currency",
            "opening_balance",
            "is_active",
        }
        explicit_nulls = sorted(
            field
            for field in non_nullable_fields
            if field in self.model_fields_set and getattr(self, field) is None
        )
        if explicit_nulls:
            raise ValueError("the following fields cannot be null: " + ", ".join(explicit_nulls))
        return self

    @model_validator(mode="after")
    def _explicit_investment_has_no_own_cash(self):
        # Validate complete payloads immediately. For partial updates (opening_balance without
        # type, or vice versa), AccountService also uses the persisted account state.
        #
        if (
            self.type == "investment"
            and self.opening_balance is not None
            and _is_nonzero_persistible_opening_balance(self.opening_balance)
        ):
            raise ValueError(
                "an investment account must have a zero opening balance; "
                "cash belongs to the reference account"
            )
        return self


class AccountRead(AccountBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool
    opened_on: dt.date | None
    closed_on: dt.date | None


class AccountBalance(BaseModel):
    account_id: int
    balance: Decimal
    currency: str
    as_of_date: str


class AccountBalanceHistoryPoint(BaseModel):
    date: dt.date
    balance: Decimal
