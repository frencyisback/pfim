"""Regression tests for canonical domain NUMERIC column representations."""

from decimal import Decimal

import pytest
from sqlalchemy import Column, Integer, MetaData, Numeric, Table, create_engine, insert, select

from app.utils.numeric_limits import (
    FX_RATE_MAX,
    NUMERIC_18_6_MAX,
    NUMERIC_18_6_QUANTUM,
    NUMERIC_18_8_QUANTUM,
    normalize_fx_rate,
    normalize_numeric_18_6,
    quantize_numeric_18_6,
)


def test_numeric_18_6_uses_deterministic_half_even_ties() -> None:
    assert normalize_numeric_18_6(Decimal("1.0000005")) == Decimal("1.000000")
    assert normalize_numeric_18_6(Decimal("1.0000015")) == Decimal("1.000002")


def test_nonzero_input_that_would_disappear_is_rejected() -> None:
    with pytest.raises(ValueError, match="zero or"):
        normalize_numeric_18_6(Decimal("0.0000005"))


def test_derived_half_micro_value_can_be_canonicalized_to_zero() -> None:
    assert quantize_numeric_18_6(Decimal("0.0000005")) == Decimal("0.000000")


def test_fx_rate_is_normalized_to_eight_decimals() -> None:
    assert normalize_fx_rate(Decimal("0.123456789")) == Decimal("0.12345679")


def test_application_limits_round_trip_at_full_scale_on_sqlite() -> None:
    """The limit reflects actual portability, not just the theoretical DDL limit."""
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    values = Table(
        "numeric_round_trip",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("amount", Numeric(18, 6), nullable=False),
        Column("rate", Numeric(18, 8), nullable=False),
    )
    metadata.create_all(engine)
    amount = NUMERIC_18_6_MAX - NUMERIC_18_6_QUANTUM
    rate = FX_RATE_MAX - NUMERIC_18_8_QUANTUM

    with engine.begin() as connection:
        connection.execute(insert(values).values(amount=amount, rate=rate))
        stored = connection.execute(select(values.c.amount, values.c.rate)).one()

    assert stored.amount == amount
    assert stored.rate == rate
    engine.dispose()


def test_values_above_the_float_safe_application_limits_are_rejected() -> None:
    with pytest.raises(ValueError, match="no greater than"):
        normalize_numeric_18_6(NUMERIC_18_6_MAX + NUMERIC_18_6_QUANTUM)
    with pytest.raises(ValueError, match="between"):
        normalize_fx_rate(FX_RATE_MAX + NUMERIC_18_8_QUANTUM)
