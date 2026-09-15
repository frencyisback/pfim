"""Industry-classification migration on a temporary database."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

PREVIOUS_REVISION = "b8d1f4a7c2e9"
CURRENT_REVISION = "c3f8a1d6e4b2"
BACKEND_DIR = Path(__file__).resolve().parents[2]


def _config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return config


def test_upgrade_and_downgrade_preserve_existing_security_data(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'security-industry.db'}"
    import app.database as database_module

    monkeypatch.setattr(database_module, "DATABASE_URL", database_url)
    config = _config()
    command.upgrade(config, PREVIOUS_REVISION)

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO securities "
                "(id, ticker, name, type, currency, sector, country, is_active) "
                "VALUES (1, 'TEST', 'Test security', 'stock', 'EUR', "
                "'Technology', 'Italy', 1)"
            )
        )
    engine.dispose()

    command.upgrade(config, CURRENT_REVISION)
    upgraded = create_engine(database_url)
    columns = {column["name"]: column for column in inspect(upgraded).get_columns("securities")}
    assert columns["industry"]["nullable"] is True
    assert columns["industry"]["type"].length == 120
    with upgraded.begin() as connection:
        row = (
            connection.execute(
                text("SELECT ticker, sector, industry, country FROM securities WHERE id = 1")
            )
            .mappings()
            .one()
        )
        assert dict(row) == {
            "ticker": "TEST",
            "sector": "Technology",
            "industry": None,
            "country": "Italy",
        }
        connection.execute(text("UPDATE securities SET industry = 'Software' WHERE id = 1"))
    upgraded.dispose()

    command.downgrade(config, PREVIOUS_REVISION)
    downgraded = create_engine(database_url)
    assert "industry" not in {
        column["name"] for column in inspect(downgraded).get_columns("securities")
    }
    with downgraded.connect() as connection:
        row = (
            connection.execute(text("SELECT ticker, sector, country FROM securities WHERE id = 1"))
            .mappings()
            .one()
        )
    assert dict(row) == {
        "ticker": "TEST",
        "sector": "Technology",
        "country": "Italy",
    }
    downgraded.dispose()
