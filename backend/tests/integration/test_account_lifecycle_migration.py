"""Failure-safe migration of local account constraints.

Each test uses a SQLite file created under ``tmp_path``. The operational
database and safety snapshot are never opened.
"""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

PREVIOUS_REVISION = "e7b3c9a5d1f4"
CURRENT_REVISION = "f2b6d8a4c1e9"
BACKEND_DIR = Path(__file__).resolve().parents[2]
CHECK_NAMES = {
    "ck_accounts_investment_cash_reference",
    "ck_accounts_noninvestment_no_reference",
}


def _config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return config


def _use_temp_database(monkeypatch, tmp_path, name: str):
    database_url = f"sqlite:///{tmp_path / name}"
    import app.database as database_module

    monkeypatch.setattr(database_module, "DATABASE_URL", database_url)
    return database_url, _config()


def _insert_account(connection, *, id_: int, name: str, type_: str, reference=None) -> None:
    connection.execute(
        text(
            "INSERT INTO accounts "
            "(id, name, type, currency, opening_balance, is_active, reference_account_id) "
            "VALUES (:id, :name, :type, 'EUR', 0, 1, :reference)"
        ),
        {"id": id_, "name": name, "type": type_, "reference": reference},
    )


def test_upgrade_adds_constraints_and_preserves_valid_accounts(tmp_path, monkeypatch):
    database_url, config = _use_temp_database(monkeypatch, tmp_path, "account-lifecycle.db")
    command.upgrade(config, PREVIOUS_REVISION)
    engine = create_engine(database_url)
    with engine.begin() as connection:
        _insert_account(connection, id_=1, name="Checking", type_="checking")
        _insert_account(
            connection, id_=2, name="Investment account", type_="investment", reference=1
        )
    engine.dispose()

    command.upgrade(config, CURRENT_REVISION)
    upgraded = create_engine(database_url)
    checks = {item["name"] for item in inspect(upgraded).get_check_constraints("accounts")}
    assert CHECK_NAMES <= checks
    with upgraded.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM accounts")) == 2

    invalid_statements = [
        (
            "INSERT INTO accounts "
            "(name, type, currency, opening_balance, is_active, reference_account_id) "
            "VALUES ('Investment account without cash', 'investment', 'EUR', 0, 1, NULL)"
        ),
        (
            "INSERT INTO accounts "
            "(name, type, currency, opening_balance, is_active, reference_account_id) "
            "VALUES ('Investment account with balance', 'investment', 'EUR', 1, 1, 1)"
        ),
        (
            "INSERT INTO accounts "
            "(name, type, currency, opening_balance, is_active, reference_account_id) "
            "VALUES ('Checking account with reference', 'checking', 'EUR', 0, 1, 1)"
        ),
    ]
    for statement in invalid_statements:
        with pytest.raises(IntegrityError), upgraded.begin() as connection:
            connection.execute(text(statement))
    upgraded.dispose()

    command.downgrade(config, PREVIOUS_REVISION)
    downgraded = create_engine(database_url)
    downgraded_checks = {
        item["name"] for item in inspect(downgraded).get_check_constraints("accounts")
    }
    assert CHECK_NAMES.isdisjoint(downgraded_checks)
    with downgraded.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM accounts")) == 2
    downgraded.dispose()


def test_upgrade_aborts_before_schema_changes_for_unsafe_account(tmp_path, monkeypatch):
    database_url, config = _use_temp_database(monkeypatch, tmp_path, "account-invalid.db")
    command.upgrade(config, PREVIOUS_REVISION)
    engine = create_engine(database_url)
    with engine.begin() as connection:
        _insert_account(connection, id_=1, name="Checking A", type_="checking")
        _insert_account(connection, id_=2, name="Checking B", type_="checking")
        connection.execute(text("UPDATE accounts SET reference_account_id = 2 WHERE id = 1"))
    engine.dispose()

    with pytest.raises(RuntimeError) as error:
        command.upgrade(config, CURRENT_REVISION)
    assert "non-investment account with reference: 1" in str(error.value)
    assert "No data was changed" in str(error.value)

    untouched = create_engine(database_url)
    checks = {item["name"] for item in inspect(untouched).get_check_constraints("accounts")}
    assert CHECK_NAMES.isdisjoint(checks)
    with untouched.connect() as connection:
        assert (
            connection.scalar(text("SELECT reference_account_id FROM accounts WHERE id = 1")) == 2
        )
    untouched.dispose()
