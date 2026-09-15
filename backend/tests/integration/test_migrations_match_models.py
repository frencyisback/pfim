"""Alembic migrations must describe the same schema as the ORM models.

Most tests use Base.metadata.create_all because it is instant. Production
always uses Alembic (README, ADR/005), so comparing both paths catches a
model column missing from a migration before startup fails with
no such column.

This test runs alembic upgrade head on an empty database and compares
the result with Base.metadata, table by table and column by column.
"""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

import app.models  # noqa: F401  (populate Base.metadata with every table)
from app.database import Base

BACKEND_DIR = Path(__file__).resolve().parents[2]

# Alembic's technical table exists only in the migrated database by definition.
ALEMBIC_BOOKKEEPING = {"alembic_version"}


@pytest.fixture(scope="module")
def migrated_inspector(tmp_path_factory):
    """A schema built by applying all migrations, starting with the first."""
    db_path = tmp_path_factory.mktemp("migrated") / "pfim.db"
    url = f"sqlite:///{db_path}"

    # migrations/env.py reads the URL from app.database: replace it there
    # to target a disposable database without touching .env.
    import app.database as database_module

    original_url = database_module.DATABASE_URL
    database_module.DATABASE_URL = url
    try:
        config = Config(str(BACKEND_DIR / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
        command.upgrade(config, "head")
    finally:
        database_module.DATABASE_URL = original_url

    return inspect(create_engine(url))


@pytest.fixture(scope="module")
def models_inspector(tmp_path_factory):
    """The schema described by the ORM models, without Alembic."""
    db_path = tmp_path_factory.mktemp("models") / "pfim.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    return inspect(engine)


def _columns(inspector, table: str) -> dict[str, tuple[str, bool]]:
    return {c["name"]: (str(c["type"]), c["nullable"]) for c in inspector.get_columns(table)}


def test_migrations_create_exactly_the_tables_of_the_models(migrated_inspector, models_inspector):
    migrated = set(migrated_inspector.get_table_names()) - ALEMBIC_BOOKKEEPING
    from_models = set(models_inspector.get_table_names())

    assert migrated == from_models, (
        f"only in migrations: {sorted(migrated - from_models)}; "
        f"only in models: {sorted(from_models - migrated)}"
    )


def test_every_table_has_the_same_columns(migrated_inspector, models_inspector):
    for table in sorted(models_inspector.get_table_names()):
        migrated = _columns(migrated_inspector, table)
        from_models = _columns(models_inspector, table)
        assert migrated == from_models, (
            f"table '{table}' differs between migrations and models: "
            f"migrated={migrated}, models={from_models}"
        )


def test_the_indexes_that_the_models_declare_exist_in_the_migrated_schema(
    migrated_inspector, models_inspector
):
    """Indexes are a performance choice in the specification (§12.3). Missing migration indexes leave the app working but increasingly slow as data grows; explicit checks catch this early."""
    for table in sorted(models_inspector.get_table_names()):
        expected = {tuple(index["column_names"]) for index in models_inspector.get_indexes(table)}
        actual = {tuple(index["column_names"]) for index in migrated_inspector.get_indexes(table)}
        assert expected <= actual, (
            f"table '{table}' is missing indexes in the migrated schema "
            f"declared by models: missing {sorted(expected - actual)}"
        )


def test_the_seed_data_only_the_migrations_carry_is_present(migrated_inspector):
    """Migrations install technical tax defaults (ADR/005). Categories and CSV import profiles start empty and are configured by the user."""
    engine = migrated_inspector.engine
    with engine.connect() as connection:
        from sqlalchemy import text

        categories = connection.execute(text("SELECT COUNT(*) FROM categories")).scalar()
        profiles = connection.execute(text("SELECT COUNT(*) FROM csv_import_profiles")).scalar()
        rates = connection.execute(text("SELECT COUNT(*) FROM tax_settings")).scalar()

    assert categories == 0, "a new database must not contain preset categories"
    assert profiles == 0, "a new database must not contain preset import profiles"
    assert rates > 0, "no default tax rate: seed was not applied"
