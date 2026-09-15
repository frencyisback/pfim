"""One transaction per request: all writes or none.

Recording a sale touches four tables: trade, tax event, cash movement, and
price history. Separate commits previously left a sale without its cash
movement after an intermediate failure, an inconsistent state no screen
reported as incomplete.

Commit now happens once, when the request exits (app.database.get_db).
"""

import sqlite3
from decimal import Decimal

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.database import get_db
from app.main import app as pfim_app
from app.utils.errors import PFIMError


def _accounts(client):
    ref = client.post(
        "/api/v1/accounts",
        json={"name": "Checking", "type": "checking", "opened_on": "2000-01-01"},
    ).json()["id"]
    dep = client.post(
        "/api/v1/accounts",
        json={
            "name": "Investment account",
            "type": "investment",
            "reference_account_id": ref,
            "opened_on": "2000-01-01",
        },
    ).json()["id"]
    return ref, dep


def _security(client, ticker="AAA"):
    return client.post(
        "/api/v1/securities",
        json={"ticker": ticker, "name": ticker, "type": "stock", "currency": "EUR"},
    ).json()["id"]


class TestCompositeWriteIsAtomic:
    def test_a_trade_writes_all_its_side_effects(self, client):
        """Normal case: all four effects are present."""
        ref, dep = _accounts(client)
        sec = _security(client)
        client.post(
            "/api/v1/trades",
            json={
                "security_id": sec,
                "account_id": dep,
                "type": "buy",
                "date": "2026-01-10",
                "quantity": 10,
                "price": 100,
                "currency": "EUR",
            },
        )

        assert len(client.get("/api/v1/trades").json()) == 1
        assert client.get("/api/v1/transactions").json()["total"] == 1
        assert len(client.get(f"/api/v1/prices/{sec}").json()) == 1
        assert Decimal(client.get(f"/api/v1/accounts/{ref}/balance").json()["balance"]) == -1000

    def test_a_failure_leaves_nothing_behind(self, client, monkeypatch):
        """An intermediate failure must leave NOTHING partially written.

        Fail historical price recording, the final step. Before the single
        transaction, the trade, tax event, and cash movement were already
        committed and would have survived this error.
        """
        ref, dep = _accounts(client)
        sec = _security(client)

        import app.services.trade_service as trade_service_module

        def _boom(self, trade):
            raise RuntimeError("simulated error after previous writes")

        monkeypatch.setattr(trade_service_module.TradeService, "_record_trade_price", _boom)

        with pytest.raises(RuntimeError):
            client.post(
                "/api/v1/trades",
                json={
                    "security_id": sec,
                    "account_id": dep,
                    "type": "buy",
                    "date": "2026-01-10",
                    "quantity": 10,
                    "price": 100,
                    "currency": "EUR",
                },
            )

        monkeypatch.undo()
        assert client.get("/api/v1/trades").json() == []
        assert client.get("/api/v1/transactions").json()["total"] == 0
        assert client.get("/api/v1/tax-events").json() == []
        assert Decimal(client.get(f"/api/v1/accounts/{ref}/balance").json()["balance"]) == 0

    def test_a_rejected_request_leaves_nothing_behind(self, client, monkeypatch):
        """Application rejection (409 short sale) must also leave the database unchanged."""
        ref, dep = _accounts(client)
        sec = _security(client)

        resp = client.post(
            "/api/v1/trades",
            json={
                "security_id": sec,
                "account_id": dep,
                "type": "sell",
                "date": "2026-01-10",
                "quantity": 10,
                "price": 100,
                "currency": "EUR",
            },
        )

        assert resp.status_code == 409
        assert client.get("/api/v1/trades").json() == []
        assert client.get("/api/v1/transactions").json()["total"] == 0


def test_commit_failure_is_reported_before_success_response(monkeypatch):
    """A COMMIT error must produce 503 rather than a false 201.

    This regression uses an isolated app and fake session without opening
    a database. FastAPI's default request scope tears down the dependency
    after sending the response; function scope does it before, allowing
    the error handler to replace the success response.
    """

    class CommitFailureSession:
        commit_attempted = False
        rolled_back = False
        closed = False

        def connection(self, *, execution_options):
            return self

        def commit(self):
            self.commit_attempted = True
            raise OperationalError(
                "COMMIT",
                {},
                sqlite3.OperationalError("database is busy"),
            )

        def rollback(self):
            self.rolled_back = True

        def close(self):
            self.closed = True

    session = CommitFailureSession()
    monkeypatch.setattr("app.database.SessionLocal", lambda: session)

    isolated_app = FastAPI()

    @isolated_app.exception_handler(PFIMError)
    def handle_pfim_error(request: Request, exc: PFIMError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error_code": exc.error_code,
                "message": exc.message,
                "detail": exc.detail,
            },
        )

    @isolated_app.post("/write", status_code=201)
    def write(db: Session = Depends(get_db, scope="function")) -> dict[str, bool]:
        assert db is session
        return {"accepted": True}

    response = TestClient(isolated_app, raise_server_exceptions=False).post("/write")

    assert response.status_code == 503
    assert response.json()["error_code"] == "DATABASE_BUSY"
    assert session.commit_attempted is True
    assert session.rolled_back is True
    assert session.closed is True


def test_every_database_route_commits_before_the_response_is_sent():
    """Prevent a new router from reverting to request scope."""

    routes = []
    for route in pfim_app.routes:
        if isinstance(route, APIRoute):
            routes.append(route)
        elif hasattr(route, "original_router"):
            # FastAPI 0.141 retains included APIRouters in lazy wrappers.
            routes.extend(
                candidate
                for candidate in route.original_router.routes
                if isinstance(candidate, APIRoute)
            )
    dependencies = [
        dependency
        for route in routes
        for dependency in route.dependant.dependencies
        if dependency.call is get_db
    ]

    assert dependencies, "no route with a database dependency found"
    assert all(dependency.scope == "function" for dependency in dependencies)


class TestReferentialIntegrity:
    def test_deleting_a_trade_removes_its_costs(self, client):
        """Costs must not outlive their trades: with FK constraints enabled, they would reference missing rows."""
        _, dep = _accounts(client)
        sec = _security(client)
        trade = client.post(
            "/api/v1/trades",
            json={
                "security_id": sec,
                "account_id": dep,
                "type": "buy",
                "date": "2026-01-10",
                "quantity": 10,
                "price": 100,
                "currency": "EUR",
            },
        ).json()
        client.post(
            f"/api/v1/trades/{trade['id']}/costs",
            json={"cost_type": "commission", "amount": 5, "currency": "EUR"},
        )

        assert client.delete(f"/api/v1/trades/{trade['id']}").status_code == 204
        assert client.get("/api/v1/trades").json() == []

    def test_deleting_a_security_removes_its_prices(self, client):
        """Price history without its security has no meaning."""
        sec = _security(client)
        client.post(
            "/api/v1/prices",
            json={"security_id": sec, "date": "2026-01-10", "price_close": 100},
        )

        assert client.delete(f"/api/v1/securities/{sec}").status_code == 204
        assert client.get(f"/api/v1/prices/{sec}").json() == []


class TestValidationErrorFormat:
    def test_validation_errors_use_the_standard_error_schema(self, client):
        """Specification §3.3: every error has error_code, message, and detail.

        Validation errors previously used FastAPI's default format without
        message, making the interface show API error 422 instead of the
        useful reason for rejection."""
        resp = client.post("/api/v1/accounts", json={"name": "", "type": "nonexistent-type"})

        assert resp.status_code == 422
        body = resp.json()
        assert body["error_code"] == "VALIDATION_ERROR"
        assert body["message"]
        assert "detail" in body

    def test_the_message_names_the_offending_field(self, client):
        """A message must identify the invalid field to help the user correct it."""
        resp = client.post(
            "/api/v1/accounts",
            json={"name": "Checking", "type": "checking", "currency": "TOO-LONG"},
        )

        assert resp.status_code == 422
        assert "currency" in resp.json()["message"]

    def test_application_errors_keep_their_own_schema(self, client):
        """The added handler must not change application errors."""
        body = client.get("/api/v1/accounts/9999/balance").json()
        assert body["error_code"] == "NOT_FOUND"
        assert "9999" in body["message"]
