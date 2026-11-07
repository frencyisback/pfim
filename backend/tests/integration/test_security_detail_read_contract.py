"""Security detail consumes existing read APIs and same-revision backups.

All data is synthetic. A disposable, Alembic-built SQLite database exercises
the actual schema and restore path; no operational database or backup is used.
The existing history API intentionally includes future observations. The new
frontend owns its through-today display filter and must not change this API.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

import app.database as database_module
from app.database import begin_session_transaction, configure_sqlite_engine, get_db
from app.main import app
from app.maintenance import MaintenanceGate
from app.models import FxRate, Price, Security
from app.schema_guard import code_alembic_heads
from app.schemas.backup import RestoreRequest
from app.services.backup_service import BackupService
from app.services.restore_service import RestoreService

BACKEND_DIR = Path(__file__).resolve().parents[2]
EUR_ID, USD_ID, INACTIVE_ID, EMPTY_ID = 101, 102, 103, 104


@dataclass
class DetailDatabase:
    client: TestClient
    engine: Engine
    path: Path
    revision: str
    today: dt.date


def _database_dump(path: Path) -> tuple[str, ...]:
    """Read both schema and every persisted row without opening a writable file."""
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as connection:
        return tuple(connection.iterdump())


def _get_json(client: TestClient, path: str):
    response = client.get(f"/api/v1{path}")
    assert response.status_code == 200, response.text
    return response.json()


def _detail_payload(client: TestClient) -> dict:
    return {
        "securities": _get_json(client, "/securities"),
        "prices": {
            security_id: _get_json(client, f"/prices/{security_id}")
            for security_id in (EUR_ID, USD_ID, INACTIVE_ID, EMPTY_ID)
        },
    }


@pytest.fixture
def detail_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "security-detail-test.db"
    url = f"sqlite:///{path}"
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    # env.py imports this URL; confine the override to migration execution.
    with monkeypatch.context() as migration_patch:
        migration_patch.setattr(database_module, "DATABASE_URL", url)
        command.upgrade(config, "head")

    (revision,) = code_alembic_heads()
    target_engine = configure_sqlite_engine(
        create_engine(url, connect_args={"check_same_thread": False})
    )
    sessions = sessionmaker(
        bind=target_engine, autocommit=False, autoflush=False, expire_on_commit=False
    )
    today = dt.date.today()
    with sessions.begin() as db:
        db.add_all(
            [
                Security(
                    id=EUR_ID,
                    ticker="EUR",
                    name="Euro security",
                    type="stock",
                    currency="EUR",
                    is_active=True,
                ),
                Security(
                    id=USD_ID,
                    ticker="USD",
                    name="Dollar security",
                    type="stock",
                    currency="USD",
                    sector="Technology",
                    industry="Software",
                    country="US",
                    notes="Preserved but not displayed in detail",
                    is_active=True,
                ),
                Security(
                    id=INACTIVE_ID,
                    ticker="OLD",
                    name="Inactive legacy ETF",
                    type="etf",
                    currency="EUR",
                    is_active=False,
                ),
                Security(
                    id=EMPTY_ID,
                    ticker="EMPTY",
                    name="No recorded prices",
                    type="bond",
                    currency="EUR",
                    is_active=True,
                ),
            ]
        )
        db.flush()
        # Insert out of order. Gaps and a future point must survive unchanged.
        db.add_all(
            [
                Price(
                    security_id=USD_ID,
                    date=today,
                    price_close=Decimal("120"),
                    fx_rate=Decimal("0.85"),
                    price_close_eur=Decimal("102"),
                    source="manual",
                ),
                Price(
                    security_id=USD_ID,
                    date=today - dt.timedelta(days=40),
                    price_close=Decimal("100"),
                    fx_rate=Decimal("0.8"),
                    price_close_eur=Decimal("80"),
                    source="csv_import",
                ),
                Price(
                    security_id=USD_ID,
                    date=today + dt.timedelta(days=20),
                    price_close=Decimal("125"),
                    fx_rate=Decimal("0.8"),
                    price_close_eur=Decimal("100"),
                    source="manual",
                ),
                Price(
                    security_id=EUR_ID,
                    date=today,
                    price_close=Decimal("50.123456"),
                    fx_rate=Decimal("1"),
                    price_close_eur=Decimal("50.123456"),
                    source="manual",
                ),
                Price(
                    security_id=INACTIVE_ID,
                    date=today - dt.timedelta(days=10),
                    price_close=Decimal("43"),
                    fx_rate=Decimal("1"),
                    price_close_eur=Decimal("43"),
                    source="csv_import",
                ),
                # A different current FX rate must never reprice saved history.
                FxRate(
                    date=today,
                    from_currency="USD",
                    to_currency="EUR",
                    rate=Decimal("0.5"),
                    source="manual",
                ),
            ]
        )

    def temporary_get_db(request: Request):
        db = sessions()
        try:
            begin_session_transaction(
                db, immediate=request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}
            )
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    monkeypatch.setitem(app.dependency_overrides, get_db, temporary_get_db)
    # No lifespan context: the application engine is deliberately not this
    # temporary engine. Only the explicitly overridden read dependency is used.
    client = TestClient(app, base_url="http://localhost")
    try:
        yield DetailDatabase(client, target_engine, path, revision, today)
    finally:
        client.close()
        target_engine.dispose()


def test_detail_reads_preserve_saved_euro_prices_dates_sources_and_database(detail_database):
    fixture = detail_database
    before = _database_dump(fixture.path)
    statements: list[str] = []

    def record_statement(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.lstrip().split(maxsplit=1)[0].upper())

    event.listen(fixture.engine, "before_cursor_execute", record_statement)
    try:
        payload = _detail_payload(fixture.client)
    finally:
        event.remove(fixture.engine, "before_cursor_execute", record_statement)

    assert statements and set(statements) <= {"BEGIN", "SELECT"}
    assert _database_dump(fixture.path) == before
    by_id = {security["id"]: security for security in payload["securities"]}
    assert set(by_id) == {EUR_ID, USD_ID, INACTIVE_ID, EMPTY_ID}
    assert by_id[INACTIVE_ID]["is_active"] is False
    assert by_id[INACTIVE_ID]["type"] == "etf"
    assert by_id[EMPTY_ID]["isin"] is None

    history = payload["prices"][USD_ID]
    assert [row["date"] for row in history] == [
        (fixture.today - dt.timedelta(days=40)).isoformat(),
        fixture.today.isoformat(),
        (fixture.today + dt.timedelta(days=20)).isoformat(),
    ]
    assert [Decimal(row["price_close_eur"]) for row in history] == [
        Decimal("80"),
        Decimal("102"),
        Decimal("100"),
    ]
    assert [Decimal(row["price_close"]) for row in history] == [
        Decimal("100"),
        Decimal("120"),
        Decimal("125"),
    ]
    assert [row["source"] for row in history] == ["csv_import", "manual", "manual"]
    assert all(row["security_id"] == USD_ID for row in history)
    assert Decimal(payload["prices"][EUR_ID][0]["price_close_eur"]) == Decimal("50.123456")


def test_detail_history_distinguishes_empty_inactive_and_other_securities(detail_database):
    client = detail_database.client
    assert _get_json(client, f"/prices/{EMPTY_ID}") == []
    assert _get_json(client, "/prices/999999") == []
    inactive = _get_json(client, f"/prices/{INACTIVE_ID}")
    assert len(inactive) == 1
    assert inactive[0]["security_id"] == INACTIVE_ID
    assert Decimal(inactive[0]["price_close_eur"]) == Decimal("43")
    active_ids = {row["id"] for row in _get_json(client, "/securities?only_active=true")}
    assert active_ids == {EUR_ID, USD_ID, EMPTY_ID}


def test_detail_data_round_trips_through_existing_backup_and_restore(detail_database):
    fixture = detail_database
    original_payload = _detail_payload(fixture.client)
    original_dump = _database_dump(fixture.path)
    backups = BackupService(
        db_path=fixture.path, backup_enabled=True, expected_revision=fixture.revision
    )
    candidate = backups.create_backup()
    candidate_path = fixture.path.parent / candidate.filename
    manifest_path = fixture.path.parent / candidate.manifest_filename
    original_backup_bytes = candidate_path.read_bytes()
    original_manifest_bytes = manifest_path.read_bytes()

    with fixture.engine.begin() as connection:
        connection.execute(text("UPDATE securities SET name = 'Changed after backup'"))
        connection.execute(text("DELETE FROM prices"))
    assert _get_json(fixture.client, f"/prices/{USD_ID}") == []

    restore = RestoreService(
        backup_service=backups,
        engine=fixture.engine,
        gate=MaintenanceGate(),
        restore_enabled=True,
        quiesce_timeout=2,
    )
    result = restore.restore_backup(
        candidate.filename,
        RestoreRequest(
            request_id=uuid.uuid4(),
            expected_sha256=candidate.sha256,
            confirmation=f"RESTORE {candidate.filename}",
        ),
        current_request_tracked=False,
    )

    assert result.restored is True
    assert result.alembic_revision == candidate.alembic_revision == fixture.revision
    assert result.pre_restore_backup is not None
    assert _detail_payload(fixture.client) == original_payload
    assert _database_dump(fixture.path) == original_dump
    assert candidate_path.read_bytes() == original_backup_bytes
    assert manifest_path.read_bytes() == original_manifest_bytes
