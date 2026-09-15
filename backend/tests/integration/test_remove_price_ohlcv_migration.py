"""Regression test for the migration removing OHLCV from prices.

Using only a temporary SQLite database, start from the preceding revision,
insert a complete price, and verify upgrade and downgrade rebuild the table
without losing fields that remain supported.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

PREVIOUS_REVISION = "b7e4d1c9a3f2"
CURRENT_REVISION = "f6c4a2d8e1b9"
REMOVED_COLUMNS = {"price_open", "price_high", "price_low", "volume"}
BACKEND_DIR = Path(__file__).resolve().parents[2]


def _alembic_config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return config


def _assert_price_and_constraints_are_preserved(engine) -> None:
    schema = inspect(engine)
    columns = {column["name"] for column in schema.get_columns("prices")}
    assert REMOVED_COLUMNS.isdisjoint(columns)
    assert {
        "id",
        "security_id",
        "date",
        "price_close",
        "fx_rate",
        "price_close_eur",
        "source",
        "imported_at",
    } <= columns

    unique_columns = {
        tuple(constraint["column_names"]) for constraint in schema.get_unique_constraints("prices")
    }
    assert ("security_id", "date") in unique_columns

    foreign_keys = schema.get_foreign_keys("prices")
    assert any(
        foreign_key["constrained_columns"] == ["security_id"]
        and foreign_key["referred_table"] == "securities"
        and foreign_key["referred_columns"] == ["id"]
        for foreign_key in foreign_keys
    )

    with engine.connect() as connection:
        row = (
            connection.execute(
                text(
                    "SELECT id, security_id, date, price_close, fx_rate, "
                    "price_close_eur, source FROM prices WHERE id = 7"
                )
            )
            .mappings()
            .one()
        )

    assert row["id"] == 7
    assert row["security_id"] == 3
    assert str(row["date"]) == "2026-01-15"
    assert float(row["price_close"]) == 123.45
    assert float(row["fx_rate"]) == 0.92
    assert float(row["price_close_eur"]) == 113.574
    assert row["source"] == "csv_import"


def test_migration_removes_only_ohlcv_and_preserves_price_rows(tmp_path, monkeypatch):
    db_path = tmp_path / "ohlcv_migration.db"
    database_url = f"sqlite:///{db_path}"

    # migrations/env.py reads this value instead of the static alembic.ini value.
    # The monkeypatch is test-local and always points to tmp_path.
    import app.database as database_module

    monkeypatch.setattr(database_module, "DATABASE_URL", database_url)
    config = _alembic_config()
    command.upgrade(config, PREVIOUS_REVISION)

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO securities "
                "(id, ticker, name, type, currency, is_active) "
                "VALUES (3, 'TEST', 'Test security', 'stock', 'USD', 1)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO prices "
                "(id, security_id, date, price_close, price_open, price_high, "
                "price_low, volume, source, fx_rate, price_close_eur) "
                "VALUES (7, 3, '2026-01-15', 123.45, 120, 125, 119, 4567, "
                "'csv_import', 0.92, 113.574)"
            )
        )
    engine.dispose()

    command.upgrade(config, CURRENT_REVISION)
    upgraded_engine = create_engine(database_url)
    _assert_price_and_constraints_are_preserved(upgraded_engine)
    upgraded_engine.dispose()

    # Downgrade must allow the revision to be reapplied without losing the
    # price. Removed OHLCV values return as NULL,
    # rather than being invented.
    command.downgrade(config, PREVIOUS_REVISION)
    downgraded_engine = create_engine(database_url)
    downgraded_columns = {
        column["name"] for column in inspect(downgraded_engine).get_columns("prices")
    }
    assert REMOVED_COLUMNS <= downgraded_columns
    with downgraded_engine.connect() as connection:
        row = (
            connection.execute(
                text(
                    "SELECT price_close, price_open, price_high, price_low, volume "
                    "FROM prices WHERE id = 7"
                )
            )
            .mappings()
            .one()
        )
    assert float(row["price_close"]) == 123.45
    assert all(row[column] is None for column in REMOVED_COLUMNS)
    downgraded_engine.dispose()
