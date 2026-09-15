"""Shared integration-test fixtures: one in-memory SQLite database and one get_db override prevent test modules from overwriting each other's dependency (dependency_overrides is global to the app instance shared by all test modules)."""

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, begin_session_transaction, configure_sqlite_engine, get_db
from app.main import app
from app.security import CAPABILITY_HEADER, capability_authority

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False, "timeout": 5.0},
    poolclass=StaticPool,
)
configure_sqlite_engine(engine, busy_timeout_ms=5_000)


# Same parameters as `app.database.SessionLocal`, one by one.
#
# `autoflush=False` determines whether queries see rows that are
# still queued in memory. With the default (`True`), they do, so a
# service can find a row it has just added through a database query;
# in production, with autoflush disabled, it cannot. This distinguishes
# a CSV import that recognizes two identical rows in the same file from
# one that writes both and hits the uniqueness constraint at
# commit, after the success response has already been sent.
#
# This actual defect went unnoticed because
# this configuration differed from production: the suite verified behavior
# that the running application did not have.
TestingSessionLocal = sessionmaker(
    autocommit=False, autoflush=False, expire_on_commit=False, bind=engine
)


def _override_get_db(request: Request):
    """Mirror `app.database.get_db`: one transaction per request, commit on exit, rollback on error.

    Keep this aligned with the original: committing elsewhere here would test transaction behavior that does not exist in production.
    """
    db = TestingSessionLocal()
    try:
        begin_session_transaction(
            db,
            immediate=request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"},
        )
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(
        app,
        base_url="http://localhost",
        headers={
            "Origin": "http://localhost:5173",
            CAPABILITY_HEADER: capability_authority.issue(),
        },
    )
