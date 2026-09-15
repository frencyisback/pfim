"""A08/A09/A10/A18 regression tests using only synthetic in-memory data."""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models.category import Category
from app.models.income_event import IncomeEvent
from app.models.portfolio_cost import PortfolioCost
from app.models.price import Price
from app.models.security import Security
from app.models.trade import Trade
from app.models.transaction import Transaction
from app.repositories.category_repo import CategoryRepository
from app.services.account_service import AccountService
from tests.integration.conftest import TestingSessionLocal


def _cash(client, name="Cash"):
    response = client.post(
        "/api/v1/accounts",
        json={
            "name": name,
            "type": "checking",
            "opened_on": "2000-01-01",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _setup(client):
    cash_id = _cash(client)
    response = client.post(
        "/api/v1/accounts",
        json={
            "name": "Investment account",
            "type": "investment",
            "reference_account_id": cash_id,
            "opened_on": "2000-01-01",
        },
    )
    assert response.status_code == 201, response.text
    account_id = response.json()["id"]
    response = client.post(
        "/api/v1/securities",
        json={
            "ticker": "AUDIT",
            "name": "Security",
            "type": "stock",
            "currency": "EUR",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"], account_id, cash_id


def _trade(db, security_id, account_id, cash_id, day, type_="buy"):
    trade = Trade(
        security_id=security_id,
        account_id=account_id,
        cash_account_id=cash_id,
        date=day,
        type=type_,
        quantity=1,
        price=10,
        quote_price=10,
        currency="EUR",
        fx_rate=1,
        price_eur=10,
        total_amount=10,
        total_eur=10,
    )
    db.add(trade)
    db.flush()
    return trade


def _income(db, security_id, account_id, cash_id, day):
    income = IncomeEvent(
        security_id=security_id,
        account_id=account_id,
        cash_account_id=cash_id,
        event_type="dividend",
        payment_date=day,
        total_amount=10,
        currency="EUR",
        fx_rate=1,
        total_eur=10,
        tax_withheld=10,
        net_amount_eur=0,
    )
    db.add(income)
    db.flush()
    return income


@pytest.mark.parametrize(
    "payload",
    [
        {"name": None},
        {"is_active": None},
        {"name": ""},
        {"name": " \t "},
        {"name": "x" * 201},
        {"coupon_freq": "weekly"},
    ],
)
def test_security_invalid_update_is_422_and_leaves_record_unchanged(client, payload):
    security_id, _, _ = _setup(client)
    response = client.put(f"/api/v1/securities/{security_id}", json=payload)
    assert response.status_code == 422, response.text
    record = client.get("/api/v1/securities").json()[0]
    assert record["name"] == "Security"
    assert record["is_active"] is True
    assert record["coupon_freq"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"name": " \t "},
        {"name": "x" * 201},
        {"coupon_freq": "weekly"},
    ],
)
def test_security_invalid_create_does_not_insert(client, payload):
    response = client.post(
        "/api/v1/securities",
        json={
            "ticker": "INVALID",
            "name": "Security",
            "type": "stock",
            "currency": "EUR",
            **payload,
        },
    )
    assert response.status_code == 422, response.text
    assert client.get("/api/v1/securities").json() == []


def test_security_supported_legacy_type_and_optional_fields_round_trip(client):
    response = client.post(
        "/api/v1/securities",
        json={
            "ticker": "LEGACY",
            "name": " Legacy security ",
            "type": "etf",
            "currency": "EUR",
            "coupon_freq": "annual",
            "coupon_rate": "-1",
            "notes": "to preserve",
        },
    )
    assert response.status_code == 201, response.text
    security_id = response.json()["id"]
    response = client.put(f"/api/v1/securities/{security_id}", json={"coupon_freq": None})
    assert response.status_code == 200, response.text
    record = client.get("/api/v1/securities").json()[0]
    assert record["type"] == "etf"
    assert record["name"] == " Legacy security "
    assert record["coupon_freq"] is None
    assert record["notes"] == "to preserve"
    assert Decimal(record["coupon_rate"]) == -1


@pytest.mark.parametrize("case", ["today_future_sell", "future_pair", "future_income"])
def test_security_deactivation_separates_current_positions_and_future_sources(client, case):
    security_id, account_id, cash_id = _setup(client)
    today = dt.date.today()
    tomorrow = today + dt.timedelta(days=1)
    with TestingSessionLocal() as db:
        if case == "today_future_sell":
            _trade(db, security_id, account_id, cash_id, today)
            future = _trade(db, security_id, account_id, cash_id, tomorrow, "sell")
        elif case == "future_pair":
            _trade(db, security_id, account_id, cash_id, tomorrow)
            future = _trade(db, security_id, account_id, cash_id, tomorrow, "sell")
        else:
            future = _income(db, security_id, account_id, cash_id, tomorrow)
        future_id = future.id
        db.commit()
    response = client.put(f"/api/v1/securities/{security_id}", json={"is_active": False})
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["as_of"] == today.isoformat()
    assert len(detail["positions"]) == (1 if case == "today_future_sell" else 0)
    if case == "future_income":
        assert detail["future_income_events"] == [
            {
                "income_event_id": future_id,
                "account_id": account_id,
                "payment_date": tomorrow.isoformat(),
            }
        ]
    else:
        assert detail["future_trades"][-1]["trade_id"] == future_id
    assert client.get("/api/v1/securities").json()[0]["is_active"] is True


@pytest.mark.parametrize("same_account", [False, True])
def test_security_legacy_negative_history_cannot_be_hidden_by_offsetting_buys(client, same_account):
    security_id, account_id, cash_id = _setup(client)
    # The second account simulates a legacy reference: the global total is zero,
    # but at least one local sequence was negative before recovering.
    other_id = account_id if same_account else cash_id
    today = dt.date.today()
    with TestingSessionLocal() as db:
        sale = _trade(db, security_id, account_id, cash_id, today, "sell")
        sale_id = sale.id
        _trade(db, security_id, other_id, cash_id, today)
        db.commit()
    response = client.put(f"/api/v1/securities/{security_id}", json={"is_active": False})
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert Decimal(detail["open_quantity"]) == 0
    assert detail["inconsistent_accounts"][0]["trade_id"] == sale_id
    assert len(detail["positions"]) == (0 if same_account else 2)


def test_security_closed_today_can_deactivate_despite_future_quotes_and_maturity(client):
    security_id, account_id, cash_id = _setup(client)
    today = dt.date.today()
    future = today + dt.timedelta(days=365)
    with TestingSessionLocal() as db:
        _trade(db, security_id, account_id, cash_id, today)
        _trade(db, security_id, account_id, cash_id, today, "sell")
        _income(db, security_id, account_id, cash_id, today)
        db.get(Security, security_id).maturity_date = future
        db.add(
            Price(
                security_id=security_id,
                date=future,
                price_close=10,
                fx_rate=1,
                price_close_eur=10,
                source="csv_import",
            )
        )
        db.commit()
    response = client.put(f"/api/v1/securities/{security_id}", json={"is_active": False})
    assert response.status_code == 200, response.text
    assert response.json()["is_active"] is False
    assert (
        client.put(f"/api/v1/securities/{security_id}", json={"is_active": True}).status_code == 200
    )


@pytest.mark.parametrize(
    "existing,new", [("Expense", " exPENSE "), ("Straße", "STRASSE"), ("CAFÉ", "café")]
)
def test_category_names_are_globally_unique_with_unicode_casefold(client, existing, new):
    created = client.post("/api/v1/categories", json={"name": existing, "type": "expense"}).json()
    parent = client.post("/api/v1/categories", json={"name": "Parent", "type": "income"}).json()
    response = client.post(
        "/api/v1/categories",
        json={
            "name": new,
            "type": "income",
            "parent_id": parent["id"],
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["category_ids"] == [created["id"]]


def test_category_comparison_preserves_accents_and_internal_spaces(client):
    for name in ("Cafe", "Café", "Two spaces", "Two  spaces"):
        response = client.post("/api/v1/categories", json={"name": name, "type": "expense"})
        assert response.status_code == 201, response.text


def test_ambiguous_legacy_category_is_readable_but_import_does_not_choose(client, monkeypatch):
    cash_id = _cash(client)
    with TestingSessionLocal() as db:
        cats = [
            Category(name=name, type=type_, is_system=False)
            for name, type_ in (
                ("Straße", "expense"),
                (" STRASSE ", "income"),
                ("Valid", "expense"),
            )
        ]
        db.add_all(cats)
        db.commit()
        ids = [cat.id for cat in cats]
    assert len(client.get("/api/v1/categories").json()) == 3
    builds = []
    original = CategoryRepository.build_name_index

    def build_once(repo):
        builds.append(True)
        return original(repo)

    monkeypatch.setattr(CategoryRepository, "build_name_index", build_once)
    content = "date,description,amount,category\n2026-01-01,Ambiguous,-10,strasse\n2026-01-02,Valid,-20,Valid\n"
    args = {
        "files": {"file": ("audit.csv", content, "text/csv")},
        "data": {"account_id": cash_id, "category_column": "category"},
    }
    preview = client.post("/api/v1/transactions/import/preview", **args)
    assert preview.status_code == 200, preview.text
    assert preview.json()["error_rows"] == 1
    error = preview.json()["rows"][0]["errors"][0]
    assert "ambiguous" in error and all(str(id_) in error for id_ in ids[:2])
    imported = client.post("/api/v1/transactions/import", **args)
    assert imported.status_code == 200, imported.text
    assert imported.json() == {"imported": 1, "skipped_duplicates": 0, "errors": 1}
    assert len(builds) == 2
    with TestingSessionLocal() as db:
        assert db.scalars(select(Transaction.category_id)).all() == [ids[2]]


@pytest.mark.parametrize(
    "source,category_name,type_",
    [
        ("trade", "Security Purchase", "expense"),
        ("income", "Coupons and Dividends", "income"),
        ("transfer", "Account Transfer", "transfer"),
    ],
)
@pytest.mark.parametrize("invalid", ["ambiguous", "wrong_type", "parent"])
def test_automatic_category_conflict_rolls_back_whole_operation(
    client, source, category_name, type_, invalid
):
    security_id, account_id, cash_id = _setup(client)
    with TestingSessionLocal() as db:
        category = Category(
            name=category_name,
            type=(
                ("expense" if type_ != "expense" else "income")
                if invalid == "wrong_type"
                else type_
            ),
            is_system=False,
        )
        db.add(category)
        db.flush()
        if invalid == "ambiguous":
            db.add(Category(name=f" {category_name.upper()} ", type=type_, is_system=False))
        if invalid == "parent":
            db.add(Category(name="Child", type=type_, parent_id=category.id, is_system=False))
        db.commit()
    if source == "trade":
        path = "/api/v1/trades"
        payload = {
            "security_id": security_id,
            "account_id": account_id,
            "date": "2026-01-01",
            "type": "buy",
            "quantity": 1,
            "price": 10,
            "currency": "EUR",
        }
    elif source == "income":
        path = "/api/v1/income-events"
        payload = {
            "security_id": security_id,
            "account_id": account_id,
            "payment_date": "2026-01-01",
            "event_type": "dividend",
            "total_amount": 10,
            "currency": "EUR",
        }
    else:
        path = "/api/v1/transactions/transfer"
        payload = {
            "from_account_id": cash_id,
            "to_account_id": _cash(client, "Destination"),
            "date": "2026-01-01",
            "amount": 10,
            "currency": "EUR",
        }
    response = client.post(path, json=payload)
    assert response.status_code == 409, response.text
    with TestingSessionLocal() as db:
        for model in (Trade, IncomeEvent, Transaction, Price):
            assert db.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.parametrize("source", ["trade", "income", "cost"])
@pytest.mark.parametrize("future", [False, True])
def test_cash_source_blocks_delete_and_identity_but_only_future_blocks_archive(
    client, source, future
):
    security_id, account_id, cash_id = _setup(client)
    new_cash_id = _cash(client, "New cash")
    day = dt.date.today() + dt.timedelta(days=1 if future else -1)
    with TestingSessionLocal() as db:
        if source == "trade":
            _trade(db, security_id, account_id, cash_id, day)
        elif source == "income":
            _income(db, security_id, account_id, cash_id, day)
        else:
            db.add(
                PortfolioCost(
                    account_id=account_id,
                    cash_account_id=cash_id,
                    date=day,
                    cost_type="custody_fee",
                    amount=1,
                    currency="EUR",
                    fx_rate=1,
                    amount_eur=1,
                )
            )
        db.commit()
    response = client.put(
        f"/api/v1/accounts/{account_id}", json={"reference_account_id": new_cash_id}
    )
    assert response.status_code == 200, response.text
    key = {
        "trade": "trades_count",
        "income": "income_events_count",
        "cost": "portfolio_costs_count",
    }[source]
    response = client.delete(f"/api/v1/accounts/{cash_id}")
    assert response.status_code == 409, response.text
    assert response.json()["detail"][key] == 1
    assert response.json()["detail"]["transactions_count"] == 0
    for change in ({"opening_balance": 100}, {"type": "savings"}):
        response = client.put(f"/api/v1/accounts/{cash_id}", json=change)
        assert response.status_code == 409, response.text
        assert response.json()["detail"][key] == 1
    response = client.post(f"/api/v1/accounts/{cash_id}/deactivate")
    assert response.status_code == (409 if future else 200), response.text
    if future:
        assert response.json()["detail"][f"future_{key}"] == 1


def test_account_sources_with_same_account_and_cash_account_are_counted_once(client):
    security_id, _, cash_id = _setup(client)
    day = dt.date.today() + dt.timedelta(days=1)
    with TestingSessionLocal() as db:
        _trade(db, security_id, cash_id, cash_id, day)
        _income(db, security_id, cash_id, cash_id, day)
        db.add(
            PortfolioCost(
                account_id=cash_id,
                cash_account_id=cash_id,
                date=day,
                cost_type="custody_fee",
                amount=1,
                currency="EUR",
                fx_rate=1,
                amount_eur=1,
            )
        )
        db.commit()
        counts = AccountService(db)._account_usage_counts(cash_id)
        for key in ("trades_count", "income_events_count", "portfolio_costs_count"):
            assert counts[key] == 1
    response = client.post(f"/api/v1/accounts/{cash_id}/deactivate")
    assert response.status_code == 409
    for key in (
        "future_trades_count",
        "future_income_events_count",
        "future_portfolio_costs_count",
    ):
        assert response.json()["detail"][key] == 1
