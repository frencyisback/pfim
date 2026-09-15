"""Migration of historical cash accounts for portfolio entities.

Tests create only SQLite files under ``tmp_path``. No operational
database or authorized snapshot is opened.
"""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

PREVIOUS_REVISION = "a4c7e9b2d5f8"
CURRENT_REVISION = "b8d1f4a7c2e9"
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


def _seed_sources(connection, *, duplicate_trade_link: bool = False) -> None:
    connection.execute(
        text(
            "INSERT INTO categories (id, name, type, is_system) "
            "VALUES (1001, 'Test expense', 'expense', 0)"
        )
    )
    category_id = 1001
    connection.execute(
        text(
            "INSERT INTO accounts "
            "(id, name, type, currency, opening_balance, is_active, reference_account_id) "
            "VALUES "
            "(1001, 'Original cash', 'checking', 'EUR', 0, 1, NULL), "
            "(1002, 'Original investment account', 'investment', 'EUR', 0, 1, 1001)"
        )
    )
    connection.execute(
        text(
            "INSERT INTO securities (id, ticker, name, type, currency, is_active) "
            "VALUES (1001, 'ORIGIN', 'Origin', 'stock', 'EUR', 1)"
        )
    )
    connection.execute(
        text(
            "INSERT INTO trades "
            "(id, security_id, account_id, type, date, quantity, price, currency, "
            "fx_rate, price_eur, total_amount, total_eur) "
            "VALUES (1001, 1001, 1002, 'buy', '2026-01-01', 1, 10, 'EUR', 1, 10, 10, 10)"
        )
    )
    connection.execute(
        text(
            "INSERT INTO income_events "
            "(id, security_id, account_id, event_type, payment_date, total_amount, "
            "currency, fx_rate, total_eur, tax_withheld, net_amount_eur) "
            "VALUES (1001, 1001, 1002, 'dividend', '2026-01-02', 2, 'EUR', 1, 2, 2, 0)"
        )
    )
    connection.execute(
        text(
            "INSERT INTO portfolio_costs "
            "(id, date, cost_type, account_id, amount, currency, fx_rate, amount_eur) "
            "VALUES (1001, '2026-01-03', 'custody_fee', 1002, 1, 'EUR', 1, 1)"
        )
    )
    connection.execute(
        text(
            "INSERT INTO transactions "
            "(id, account_id, category_id, date, amount, currency, fx_rate, amount_eur, trade_id) "
            "VALUES (1001, 1001, :category_id, '2026-01-01', -10, 'EUR', 1, -10, 1001)"
        ),
        {"category_id": category_id},
    )
    connection.execute(
        text(
            "INSERT INTO transactions "
            "(id, account_id, category_id, date, amount, currency, fx_rate, amount_eur, "
            "portfolio_cost_id) "
            "VALUES (1002, 1001, :category_id, '2026-01-03', -1, 'EUR', 1, -1, 1001)"
        ),
        {"category_id": category_id},
    )
    if duplicate_trade_link:
        connection.execute(
            text(
                "INSERT INTO transactions "
                "(id, account_id, category_id, date, amount, currency, fx_rate, amount_eur, "
                "trade_id) VALUES "
                "(1003, 1001, :category_id, '2026-01-01', -1, 'EUR', 1, -1, 1001)"
            ),
            {"category_id": category_id},
        )


def test_upgrade_backfills_only_from_exact_link_and_preserves_unknown(tmp_path, monkeypatch):
    database_url, config = _use_temp_database(monkeypatch, tmp_path, "cash-origin.db")
    command.upgrade(config, PREVIOUS_REVISION)
    engine = create_engine(database_url)
    with engine.begin() as connection:
        _seed_sources(connection)
    engine.dispose()

    command.upgrade(config, CURRENT_REVISION)
    upgraded = create_engine(database_url)
    for table in ("trades", "income_events", "portfolio_costs"):
        columns = {column["name"] for column in inspect(upgraded).get_columns(table)}
        assert "cash_account_id" in columns
        targets = {
            fk["referred_table"]
            for fk in inspect(upgraded).get_foreign_keys(table)
            if fk["constrained_columns"] == ["cash_account_id"]
        }
        assert targets == {"accounts"}

    with upgraded.connect() as connection:
        assert connection.scalar(text("SELECT cash_account_id FROM trades WHERE id = 1001")) == 1001
        assert (
            connection.scalar(text("SELECT cash_account_id FROM portfolio_costs WHERE id = 1001"))
            == 1001
        )
        # Zero net income had no linked movement: using the
        # current reference would be an inference, so it remains unknown.
        assert (
            connection.scalar(text("SELECT cash_account_id FROM income_events WHERE id = 1001"))
            is None
        )
    upgraded.dispose()

    command.downgrade(config, PREVIOUS_REVISION)
    downgraded = create_engine(database_url)
    for table in ("trades", "income_events", "portfolio_costs"):
        columns = {column["name"] for column in inspect(downgraded).get_columns(table)}
        assert "cash_account_id" not in columns
        with downgraded.connect() as connection:
            assert connection.scalar(text(f"SELECT COUNT(*) FROM {table}")) == 1
    downgraded.dispose()


def test_upgrade_fails_before_schema_change_on_duplicate_source_links(tmp_path, monkeypatch):
    database_url, config = _use_temp_database(monkeypatch, tmp_path, "cash-origin-duplicate.db")
    command.upgrade(config, PREVIOUS_REVISION)
    engine = create_engine(database_url)
    with engine.begin() as connection:
        _seed_sources(connection, duplicate_trade_link=True)
    engine.dispose()

    with pytest.raises(RuntimeError, match="multiple linked transactions"):
        command.upgrade(config, CURRENT_REVISION)

    unchanged = create_engine(database_url)
    for table in ("trades", "income_events", "portfolio_costs"):
        assert "cash_account_id" not in {
            column["name"] for column in inspect(unchanged).get_columns(table)
        }
    with unchanged.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM transactions")) == 3
    unchanged.dispose()
