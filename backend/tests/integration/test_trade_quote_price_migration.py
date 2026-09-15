"""Migration of quoted price and automatic price ownership.

All databases here are temporary files. Tests also cover atomic rejection
of ambiguous legacy data: upgrade never invents historical prices.
"""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

PREVIOUS_REVISION = "c3f8a1d6e4b2"
CURRENT_REVISION = "d7b2e9f4a6c1"
BACKEND_DIR = Path(__file__).resolve().parents[2]


def _config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return config


def _use_temp_database(monkeypatch, tmp_path, filename: str):
    database_url = f"sqlite:///{tmp_path / filename}"
    import app.database as database_module

    monkeypatch.setattr(database_module, "DATABASE_URL", database_url)
    return database_url, _config()


def _seed_accounts_and_security(connection, *, security_currency: str = "EUR") -> None:
    connection.execute(
        text(
            "INSERT INTO accounts "
            "(id, name, type, currency, opening_balance, is_active, reference_account_id) "
            "VALUES "
            "(9001, 'Quote cash', 'checking', 'EUR', 0, 1, NULL), "
            "(9002, 'Quote investment account', 'investment', 'EUR', 0, 1, 9001)"
        )
    )
    connection.execute(
        text(
            "INSERT INTO securities (id, ticker, name, type, currency, is_active) "
            "VALUES (9001, 'QUOTE', 'Quoted security', 'stock', :currency, 1)"
        ),
        {"currency": security_currency},
    )


def _insert_trade(
    connection,
    *,
    trade_id: int,
    date: str,
    price: str,
    currency: str = "EUR",
    fx_rate: str = "1",
) -> None:
    price_eur = str(float(price) * float(fx_rate))
    connection.execute(
        text(
            "INSERT INTO trades "
            "(id, security_id, account_id, cash_account_id, type, date, quantity, price, "
            "currency, fx_rate, price_eur, total_amount, total_eur) "
            "VALUES (:id, 9001, 9002, 9001, 'buy', :date, 1, :price, :currency, "
            ":fx_rate, :price_eur, :price, :price_eur)"
        ),
        {
            "id": trade_id,
            "date": date,
            "price": price,
            "currency": currency,
            "fx_rate": fx_rate,
            "price_eur": price_eur,
        },
    )


def test_upgrade_backfills_quote_price_and_links_only_verifiable_prices(tmp_path, monkeypatch):
    database_url, config = _use_temp_database(monkeypatch, tmp_path, "quote-price.db")
    command.upgrade(config, PREVIOUS_REVISION)
    engine = create_engine(database_url)
    with engine.begin() as connection:
        _seed_accounts_and_security(connection)
        _insert_trade(connection, trade_id=9101, date="2026-01-01", price="10")
        _insert_trade(connection, trade_id=9102, date="2026-01-01", price="12")
        _insert_trade(connection, trade_id=9103, date="2026-04-01", price="20")
        _insert_trade(connection, trade_id=9104, date="2026-04-01", price="20")
        connection.execute(
            text(
                "INSERT INTO prices "
                "(id, security_id, date, price_close, fx_rate, price_close_eur, source) "
                "VALUES "
                "(9201, 9001, '2026-01-01', 10, 1, 10, 'trade'), "
                "(9202, 9001, '2026-02-01', 15, 1, 15, 'manual'), "
                "(9203, 9001, '2026-03-01', 16, 1, 16, 'trade'), "
                "(9204, 9001, '2026-04-01', 20, 1, 20, 'trade')"
            )
        )
    engine.dispose()

    command.upgrade(config, CURRENT_REVISION)
    upgraded = create_engine(database_url)
    columns = {column["name"]: column for column in inspect(upgraded).get_columns("trades")}
    assert columns["quote_price"]["nullable"] is False
    assert "origin_trade_id" in {
        column["name"] for column in inspect(upgraded).get_columns("prices")
    }
    with upgraded.connect() as connection:
        trades = connection.execute(text("SELECT id, quote_price FROM trades ORDER BY id")).all()
        assert [(row.id, float(row.quote_price)) for row in trades] == [
            (9101, 10.0),
            (9102, 12.0),
            (9103, 20.0),
            (9104, 20.0),
        ]
        prices = (
            connection.execute(text("SELECT id, source, origin_trade_id FROM prices ORDER BY id"))
            .mappings()
            .all()
        )
        assert [dict(row) for row in prices] == [
            {"id": 9201, "source": "trade", "origin_trade_id": 9101},
            {"id": 9202, "source": "manual", "origin_trade_id": None},
            {"id": 9203, "source": "legacy_trade_orphan", "origin_trade_id": None},
            {"id": 9204, "source": "legacy_trade_orphan", "origin_trade_id": None},
        ]
    upgraded.dispose()

    command.downgrade(config, PREVIOUS_REVISION)
    downgraded = create_engine(database_url)
    assert "quote_price" not in {
        column["name"] for column in inspect(downgraded).get_columns("trades")
    }
    assert "origin_trade_id" not in {
        column["name"] for column in inspect(downgraded).get_columns("prices")
    }
    with downgraded.connect() as connection:
        assert connection.scalar(text("SELECT source FROM prices WHERE id = 9203")) == "trade"
    downgraded.dispose()


def test_upgrade_rejects_ambiguous_legacy_trade_before_schema_change(tmp_path, monkeypatch):
    database_url, config = _use_temp_database(monkeypatch, tmp_path, "quote-ambiguous.db")
    command.upgrade(config, PREVIOUS_REVISION)
    engine = create_engine(database_url)
    with engine.begin() as connection:
        _seed_accounts_and_security(connection, security_currency="USD")
        _insert_trade(
            connection,
            trade_id=9301,
            date="2026-01-01",
            price="90",
            currency="EUR",
        )
    engine.dispose()

    with pytest.raises(RuntimeError, match="cannot be reconstructed"):
        command.upgrade(config, CURRENT_REVISION)

    unchanged = create_engine(database_url)
    assert "quote_price" not in {
        column["name"] for column in inspect(unchanged).get_columns("trades")
    }
    assert "origin_trade_id" not in {
        column["name"] for column in inspect(unchanged).get_columns("prices")
    }
    with unchanged.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM trades")) == 1
    unchanged.dispose()
