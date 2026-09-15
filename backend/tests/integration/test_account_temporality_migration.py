"""Nondestructive migration of account temporality.

Each test uses a SQLite file created under ``tmp_path`` and never opens
operational databases or safety snapshots.
"""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

PREVIOUS_REVISION = "f2b6d8a4c1e9"
CURRENT_REVISION = "a4c7e9b2d5f8"
BACKEND_DIR = Path(__file__).resolve().parents[2]
LIFECYCLE_CHECK = "ck_accounts_lifecycle_dates"


def _config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return config


def _use_temp_database(monkeypatch, tmp_path, name: str):
    database_url = f"sqlite:///{tmp_path / name}"
    import app.database as database_module

    monkeypatch.setattr(database_module, "DATABASE_URL", database_url)
    return database_url, _config()


def test_upgrade_preserves_legacy_rows_as_unknown_and_adds_check(tmp_path, monkeypatch):
    database_url, config = _use_temp_database(monkeypatch, tmp_path, "account-temporality.db")
    command.upgrade(config, PREVIOUS_REVISION)
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO accounts "
                "(id, name, type, currency, opening_balance, is_active, reference_account_id) "
                "VALUES (1, 'Legacy', 'checking', 'EUR', 42, 1, NULL)"
            )
        )
    engine.dispose()

    command.upgrade(config, CURRENT_REVISION)
    upgraded = create_engine(database_url)
    columns = {column["name"] for column in inspect(upgraded).get_columns("accounts")}
    checks = {item["name"] for item in inspect(upgraded).get_check_constraints("accounts")}
    assert {"opened_on", "closed_on"} <= columns
    assert LIFECYCLE_CHECK in checks
    assert {
        "ck_accounts_investment_cash_reference",
        "ck_accounts_noninvestment_no_reference",
    } <= checks

    with upgraded.connect() as connection:
        row = connection.execute(
            text("SELECT opening_balance, opened_on, closed_on FROM accounts WHERE id = 1")
        ).one()
        assert str(row.opening_balance) == "42"
        assert row.opened_on is None
        assert row.closed_on is None

    with pytest.raises(IntegrityError), upgraded.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO accounts "
                "(name, type, currency, opening_balance, is_active, opened_on, closed_on) "
                "VALUES ('Reversed interval', 'checking', 'EUR', 0, 0, "
                "'2026-08-20', '2026-08-19')"
            )
        )
    upgraded.dispose()

    command.downgrade(config, PREVIOUS_REVISION)
    downgraded = create_engine(database_url)
    downgraded_columns = {column["name"] for column in inspect(downgraded).get_columns("accounts")}
    assert "opened_on" not in downgraded_columns
    assert "closed_on" not in downgraded_columns
    with downgraded.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM accounts")) == 1
        assert connection.scalar(text("SELECT opening_balance FROM accounts WHERE id = 1")) == 42
    downgraded.dispose()
