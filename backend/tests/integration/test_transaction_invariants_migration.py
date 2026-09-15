"""Failure-safe migration for required categories and nonzero amounts."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

PREVIOUS_REVISION = "f6c4a2d8e1b9"
CURRENT_REVISION = "a9e5c7d2b4f1"
CHECK_NAME = "ck_transactions_amount_nonzero"
BACKEND_DIR = Path(__file__).resolve().parents[2]


def _config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return config


def _use_temp_database(monkeypatch, tmp_path, name: str):
    database_url = f"sqlite:///{tmp_path / name}"
    import app.database as database_module

    monkeypatch.setattr(database_module, "DATABASE_URL", database_url)
    return database_url, _config()


def _insert_account_and_category(connection) -> None:
    connection.execute(
        text(
            "INSERT INTO accounts "
            "(id, name, type, currency, opening_balance, is_active) "
            "VALUES (1, 'Account', 'checking', 'EUR', 0, 1)"
        )
    )
    connection.execute(
        text(
            "INSERT INTO categories (id, name, type, is_system) "
            "VALUES (100, 'Valid income', 'income', 0)"
        )
    )


def test_upgrade_preserves_rows_and_adds_not_null_and_check(tmp_path, monkeypatch):
    database_url, config = _use_temp_database(monkeypatch, tmp_path, "valid.db")
    command.upgrade(config, PREVIOUS_REVISION)
    engine = create_engine(database_url)
    with engine.begin() as connection:
        _insert_account_and_category(connection)
        connection.execute(
            text(
                "INSERT INTO transactions "
                "(id, account_id, category_id, date, amount, currency, fx_rate, amount_eur) "
                "VALUES (7, 1, 100, '2026-08-01', 25, 'EUR', 1, 25)"
            )
        )
    engine.dispose()

    command.upgrade(config, CURRENT_REVISION)
    upgraded = create_engine(database_url)
    schema = inspect(upgraded)
    category_column = next(
        column for column in schema.get_columns("transactions") if column["name"] == "category_id"
    )
    assert category_column["nullable"] is False
    assert CHECK_NAME in {
        constraint["name"] for constraint in schema.get_check_constraints("transactions")
    }
    assert {"account_id", "category_id", "date"} <= {
        index["column_names"][0] for index in schema.get_indexes("transactions")
    }
    with upgraded.connect() as connection:
        row = connection.execute(
            text("SELECT category_id, amount, amount_eur FROM transactions WHERE id = 7")
        ).one()
    assert row.category_id == 100
    assert float(row.amount) == 25
    assert float(row.amount_eur) == 25

    with pytest.raises(IntegrityError), upgraded.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO transactions "
                "(account_id, category_id, date, amount, currency, fx_rate, amount_eur) "
                "VALUES (1, 100, '2026-08-02', 0, 'EUR', 1, 0)"
            )
        )
    upgraded.dispose()

    command.downgrade(config, PREVIOUS_REVISION)
    downgraded = create_engine(database_url)
    downgraded_schema = inspect(downgraded)
    category_column = next(
        column
        for column in downgraded_schema.get_columns("transactions")
        if column["name"] == "category_id"
    )
    assert category_column["nullable"] is True
    assert CHECK_NAME not in {
        constraint["name"] for constraint in downgraded_schema.get_check_constraints("transactions")
    }
    with downgraded.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM transactions WHERE id = 7")) == 1
    downgraded.dispose()


def test_upgrade_aborts_before_schema_changes_for_null_or_zero_rows(tmp_path, monkeypatch):
    database_url, config = _use_temp_database(monkeypatch, tmp_path, "invalid.db")
    command.upgrade(config, PREVIOUS_REVISION)
    engine = create_engine(database_url)
    with engine.begin() as connection:
        _insert_account_and_category(connection)
        connection.execute(
            text(
                "INSERT INTO transactions "
                "(id, account_id, category_id, date, amount, currency, fx_rate, amount_eur) "
                "VALUES (8, 1, NULL, '2026-08-01', 10, 'EUR', 1, 10), "
                "(9, 1, 100, '2026-08-02', 0, 'EUR', 1, 0)"
            )
        )
    engine.dispose()

    with pytest.raises(RuntimeError) as error:
        command.upgrade(config, CURRENT_REVISION)

    assert "category_id NULL: 1" in str(error.value)
    assert "amount zero: 1" in str(error.value)
    assert "No backfill" in str(error.value)
    untouched = create_engine(database_url)
    category_column = next(
        column
        for column in inspect(untouched).get_columns("transactions")
        if column["name"] == "category_id"
    )
    assert category_column["nullable"] is True
    with untouched.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM transactions")) == 2
    untouched.dispose()
