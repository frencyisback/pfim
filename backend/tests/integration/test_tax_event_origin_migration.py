"""Failure-safe migration of tax-event provenance.

Use only SQLite files under tmp_path; never open the application's
configured database.
"""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

PREVIOUS_REVISION = "a9e5c7d2b4f1"
CURRENT_REVISION = "d4e8f2a6c1b9"
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


def _seed_sources(connection) -> None:
    connection.execute(
        text(
            "INSERT INTO accounts "
            "(id, name, type, currency, opening_balance, is_active) VALUES "
            "(1, 'Checking', 'checking', 'EUR', 0, 1), "
            "(2, 'Investment account', 'investment', 'EUR', 0, 1)"
        )
    )
    connection.execute(
        text(
            "INSERT INTO securities (id, ticker, name, type, currency, is_active) "
            "VALUES (1, 'ENI', 'Eni', 'stock', 'EUR', 1)"
        )
    )
    connection.execute(
        text(
            "INSERT INTO trades "
            "(id, security_id, account_id, type, date, quantity, price, currency, "
            "fx_rate, price_eur, total_amount, total_eur) VALUES "
            "(10, 1, 2, 'sell', '2026-03-01', 5, 300, 'EUR', 1, 300, 1500, 1500), "
            "(20, 1, 2, 'sell', '2026-04-01', 2, 400, 'EUR', 1, 400, 800, 800)"
        )
    )
    connection.execute(
        text(
            "INSERT INTO income_events "
            "(id, security_id, account_id, event_type, payment_date, total_amount, currency, "
            "fx_rate, total_eur, tax_withheld, net_amount_eur) "
            "VALUES (30, 1, 2, 'dividend', '2026-05-01', 100, 'EUR', 1, 100, 26, 74)"
        )
    )


def _insert_legacy_events(connection) -> None:
    connection.execute(
        text(
            "INSERT INTO tax_events "
            "(id, event_date, event_type, related_trade_id, related_income_id, description, "
            "gross_amount, tax_rate, tax_amount, net_amount, is_compensated) VALUES "
            "(1, '2026-03-01', 'capital_gain', 10, NULL, "
            " 'Capital gain realized on ENI', 1000, 26, 260, 740, 0), "
            "(2, '2026-03-01', 'other', 10, NULL, "
            " 'Linked manual note', NULL, NULL, NULL, NULL, 0), "
            "(3, '2026-02-01', 'other', NULL, NULL, "
            " 'Unlinked manual entry', 15, NULL, NULL, NULL, 0), "
            "(4, '2026-04-01', 'capital_gain', 20, NULL, "
            " 'Capital gain realized on ENI', 100, 26, 26, 74, 0), "
            "(5, '2026-04-01', 'capital_gain', 20, NULL, "
            " 'Capital gain realized on ENI', 100, 26, 26, 74, 0), "
            "(6, '2026-05-01', 'withholding', NULL, 30, "
            " 'Linked withholding', 100, 26, 26, 74, 0)"
        )
    )


def test_upgrade_backfills_only_one_unambiguous_automatic_event(tmp_path, monkeypatch):
    database_url, config = _use_temp_database(monkeypatch, tmp_path, "tax-origin.db")
    command.upgrade(config, PREVIOUS_REVISION)
    engine = create_engine(database_url)
    with engine.begin() as connection:
        _seed_sources(connection)
        _insert_legacy_events(connection)
    engine.dispose()

    command.upgrade(config, CURRENT_REVISION)
    upgraded = create_engine(database_url)
    schema = inspect(upgraded)
    origin = next(c for c in schema.get_columns("tax_events") if c["name"] == "origin")
    assert origin["nullable"] is False
    assert {
        "ck_tax_events_origin",
        "ck_tax_events_single_related_source",
        "ck_tax_events_automatic_trade_source",
    } <= {constraint["name"] for constraint in schema.get_check_constraints("tax_events")}
    automatic_index = next(
        index
        for index in schema.get_indexes("tax_events")
        if index["name"] == "uq_tax_events_automatic_trade"
    )
    # SQLite/SQLAlchemy may expose the flag as 1 rather than the Python
    # True singleton; the contract is boolean value, not object identity.
    assert bool(automatic_index["unique"])
    assert automatic_index["column_names"] == ["related_trade_id"]

    with upgraded.connect() as connection:
        origins = {
            row.id: row.origin
            for row in connection.execute(text("SELECT id, origin FROM tax_events"))
        }
    assert origins == {
        1: "automatic_trade",
        2: "legacy_unknown",
        3: "legacy_unknown",
        4: "legacy_unknown",
        5: "legacy_unknown",
        6: "legacy_unknown",
    }

    invalid_statements = [
        (
            "INSERT INTO tax_events "
            "(event_date, event_type, origin, description, is_compensated) "
            "VALUES ('2026-06-01', 'other', 'invented', 'Invalid origin', 0)"
        ),
        (
            "INSERT INTO tax_events "
            "(event_date, event_type, origin, related_trade_id, related_income_id, "
            "description, is_compensated) VALUES "
            "('2026-06-01', 'other', 'manual', 10, 30, 'Double link', 0)"
        ),
        (
            "INSERT INTO tax_events "
            "(event_date, event_type, origin, description, is_compensated) "
            "VALUES ('2026-06-01', 'capital_gain', 'automatic_trade', 'Without trade', 0)"
        ),
        (
            "INSERT INTO tax_events "
            "(event_date, event_type, origin, related_trade_id, description, is_compensated) "
            "VALUES ('2026-03-01', 'capital_gain', 'automatic_trade', 10, 'Duplicate', 0)"
        ),
    ]
    for statement in invalid_statements:
        with pytest.raises(IntegrityError), upgraded.begin() as connection:
            connection.execute(text(statement))
    upgraded.dispose()

    command.downgrade(config, PREVIOUS_REVISION)
    downgraded = create_engine(database_url)
    assert "origin" not in {
        column["name"] for column in inspect(downgraded).get_columns("tax_events")
    }
    with downgraded.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM tax_events")) == 6
    downgraded.dispose()


def test_upgrade_aborts_before_schema_changes_for_unsafe_links(tmp_path, monkeypatch):
    database_url, config = _use_temp_database(monkeypatch, tmp_path, "tax-origin-invalid.db")
    command.upgrade(config, PREVIOUS_REVISION)
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO tax_events "
                "(id, event_date, event_type, related_trade_id, related_income_id, description, "
                "is_compensated) VALUES "
                "(1, '2026-01-01', 'other', 999, 888, 'Broken double link', 0)"
            )
        )
    engine.dispose()

    with pytest.raises(RuntimeError) as error:
        command.upgrade(config, CURRENT_REVISION)
    assert "dual trade/income link: 1" in str(error.value)
    assert "linked trade does not exist: 1" in str(error.value)
    assert "linked income event does not exist: 1" in str(error.value)
    assert "No backfill" in str(error.value)

    untouched = create_engine(database_url)
    assert "origin" not in {
        column["name"] for column in inspect(untouched).get_columns("tax_events")
    }
    with untouched.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM tax_events")) == 1
    untouched.dispose()
