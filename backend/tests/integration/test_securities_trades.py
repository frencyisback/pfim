"""Integration tests: securities, trades, FIFO via API, and safeguards (specification §6.3, §6.4, §9.1)."""

import datetime as dt
import io
from decimal import Decimal


def _make_security(client, ticker="ENI.MI") -> int:
    return client.post(
        "/api/v1/securities",
        json={"ticker": ticker, "name": "Eni SpA", "type": "stock", "currency": "EUR"},
    ).json()["id"]


def _make_account(client) -> int:
    """Investment account with an automatically created reference account."""
    return _make_account_with_reference(client)[0]


def _make_account_with_reference(client) -> tuple[int, int]:
    """Return (investment_account_id, reference_account_id): trade-generated transactions belong to the second, never the first (§5.2)."""
    checking = client.post(
        "/api/v1/accounts",
        json={"name": "Checking Account", "type": "checking", "opened_on": "2000-01-01"},
    ).json()
    invest = client.post(
        "/api/v1/accounts",
        json={
            "name": "Securities Account",
            "type": "investment",
            "reference_account_id": checking["id"],
            "opened_on": "2000-01-01",
        },
    ).json()
    return invest["id"], checking["id"]


def test_create_security_duplicate_ticker_returns_409(client):
    client.post(
        "/api/v1/securities",
        json={"ticker": "AAPL", "name": "Apple", "type": "stock", "currency": "USD"},
    )
    resp = client.post(
        "/api/v1/securities",
        json={"ticker": "AAPL", "name": "Apple Inc", "type": "stock", "currency": "USD"},
    )
    assert resp.status_code == 409


def test_security_classification_fields_round_trip_and_can_be_cleared(client):
    created = client.post(
        "/api/v1/securities",
        json={
            "ticker": "CLASS.MI",
            "name": "Classified security",
            "type": "stock",
            "currency": "EUR",
            "sector": "Technology",
            "industry": "Software",
            "country": "Italy",
        },
    )
    assert created.status_code == 201
    security = created.json()
    assert (security["sector"], security["industry"], security["country"]) == (
        "Technology",
        "Software",
        "Italy",
    )

    updated = client.put(
        f"/api/v1/securities/{security['id']}",
        json={"sector": "Services", "industry": None, "country": "France"},
    )
    assert updated.status_code == 200
    assert (updated.json()["sector"], updated.json()["industry"], updated.json()["country"]) == (
        "Services",
        None,
        "France",
    )


def test_security_numeric_metadata_is_normalized_on_create_and_update(client):
    created = client.post(
        "/api/v1/securities",
        json={
            "ticker": "BOND.MI",
            "name": "Bond",
            "type": "bond",
            "currency": "EUR",
            "coupon_rate": "3.12345",
            "face_value": "1000.1234565",
        },
    )

    assert created.status_code == 201, created.text
    security = created.json()
    assert Decimal(security["coupon_rate"]) == Decimal("3.1234")
    assert Decimal(security["face_value"]) == Decimal("1000.123456")

    updated = client.put(
        f"/api/v1/securities/{security['id']}",
        json={"coupon_rate": "3.12355", "face_value": "1000.1234575"},
    )
    assert updated.status_code == 200, updated.text
    assert Decimal(updated.json()["coupon_rate"]) == Decimal("3.1236")
    assert Decimal(updated.json()["face_value"]) == Decimal("1000.123458")


def test_security_numeric_metadata_rejects_values_lost_at_declared_scale(client):
    response = client.post(
        "/api/v1/securities",
        json={
            "ticker": "TINY.MI",
            "name": "Metadata too small",
            "type": "bond",
            "currency": "EUR",
            "coupon_rate": "0.00001",
            "face_value": "0.0000001",
        },
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "VALIDATION_ERROR"
    assert response.json()["detail"]["field"] == "coupon_rate"
    assert client.get("/api/v1/securities").json() == []


def test_fifo_position_via_api(client):
    sec_id = _make_security(client)
    acc_id = _make_account(client)

    client.post(
        "/api/v1/trades",
        json={
            "security_id": sec_id,
            "account_id": acc_id,
            "type": "buy",
            "date": "2026-01-01",
            "quantity": 100,
            "price": 10,
            "currency": "EUR",
        },
    )
    client.post(
        "/api/v1/trades",
        json={
            "security_id": sec_id,
            "account_id": acc_id,
            "type": "buy",
            "date": "2026-02-01",
            "quantity": 50,
            "price": 12,
            "currency": "EUR",
        },
    )
    resp = client.post(
        "/api/v1/trades",
        json={
            "security_id": sec_id,
            "account_id": acc_id,
            "type": "sell",
            "date": "2026-03-01",
            "quantity": 120,
            "price": 15,
            "currency": "EUR",
        },
    )
    assert resp.status_code == 201

    position = client.get(f"/api/v1/portfolio/{sec_id}").json()
    assert float(position["quantity"]) == 30.0
    # 100 units at 10 sold (realized 100*5=500) + 20 units at 12 sold (realized 20*3=60)
    assert float(position["realized_gain_loss"]) == 560.0
    assert float(position["average_cost"]) == 12.0


def test_oversell_returns_409(client):
    sec_id = _make_security(client)
    acc_id = _make_account(client)
    client.post(
        "/api/v1/trades",
        json={
            "security_id": sec_id,
            "account_id": acc_id,
            "type": "buy",
            "date": "2026-01-01",
            "quantity": 10,
            "price": 10,
            "currency": "EUR",
        },
    )
    resp = client.post(
        "/api/v1/trades",
        json={
            "security_id": sec_id,
            "account_id": acc_id,
            "type": "sell",
            "date": "2026-02-01",
            "quantity": 50,
            "price": 10,
            "currency": "EUR",
        },
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "CONFLICT"


def test_delete_trade_blocked_if_dependent_sell_exists(client):
    sec_id = _make_security(client)
    acc_id = _make_account(client)
    buy = client.post(
        "/api/v1/trades",
        json={
            "security_id": sec_id,
            "account_id": acc_id,
            "type": "buy",
            "date": "2026-01-01",
            "quantity": 10,
            "price": 10,
            "currency": "EUR",
        },
    ).json()
    client.post(
        "/api/v1/trades",
        json={
            "security_id": sec_id,
            "account_id": acc_id,
            "type": "sell",
            "date": "2026-02-01",
            "quantity": 10,
            "price": 12,
            "currency": "EUR",
        },
    )
    resp = client.delete(f"/api/v1/trades/{buy['id']}")
    assert resp.status_code == 409


def test_portfolio_valuation_with_price_import(client):
    sec_id = _make_security(client)
    acc_id = _make_account(client)
    client.post(
        "/api/v1/trades",
        json={
            "security_id": sec_id,
            "account_id": acc_id,
            "type": "buy",
            "date": "2026-01-01",
            "quantity": 100,
            "price": 14,
            "currency": "EUR",
        },
    )

    csv_content = "date;ticker;close\n2026-07-01;ENI.MI;17.20\n"
    file = io.BytesIO(csv_content.encode("utf-8"))
    import_resp = client.post(
        "/api/v1/prices/import", files={"file": ("prices.csv", file, "text/csv")}
    )
    assert import_resp.json() == {
        "imported": 1,
        "updated": 0,
        "skipped_unrecognized_ticker": 0,
        "errors": 0,
    }

    latest_price = client.get(f"/api/v1/prices/{sec_id}/latest").json()
    assert set(latest_price) == {
        "id",
        "security_id",
        "date",
        "price_close",
        "fx_rate",
        "price_close_eur",
        "source",
        "origin_trade_id",
    }

    position = client.get(f"/api/v1/portfolio/{sec_id}").json()
    assert float(position["current_price"]) == 17.20
    assert float(position["current_value"]) == 1720.0
    assert round(float(position["unrealized_gain_loss"]), 2) == 320.0


def test_price_import_ignores_legacy_ohlcv_columns(client):
    """Old files remain importable, but OHLCV is no longer part of the contract."""
    sec_id = _make_security(client)
    csv_content = (
        "date;ticker;close;open;high;low;volume\n"
        "2026-07-01;ENI.MI;17.20;17.00;17.30;16.90;1000000\n"
    )

    response = client.post(
        "/api/v1/prices/import",
        files={"file": ("prices-legacy.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")},
    )

    assert response.status_code == 200
    assert response.json()["imported"] == 1
    latest = client.get(f"/api/v1/prices/{sec_id}/latest").json()
    assert set(latest) == {
        "id",
        "security_id",
        "date",
        "price_close",
        "fx_rate",
        "price_close_eur",
        "source",
        "origin_trade_id",
    }


def test_fx_rate_import_calculates_reciprocal(client):
    csv_content = "date;from;to;rate\n2026-07-01;USD;EUR;0.9145\n"
    file = io.BytesIO(csv_content.encode("utf-8"))
    resp = client.post("/api/v1/fx-rates/import", files={"file": ("fx.csv", file, "text/csv")})
    body = resp.json()
    assert body["imported"] == 1
    assert body["reciprocal_calculated"] == 1

    rates = client.get("/api/v1/fx-rates").json()
    assert len(rates) == 2


def test_trade_cost_can_be_added(client):
    sec_id = _make_security(client)
    acc_id = _make_account(client)
    trade = client.post(
        "/api/v1/trades",
        json={
            "security_id": sec_id,
            "account_id": acc_id,
            "type": "buy",
            "date": "2026-01-01",
            "quantity": 10,
            "price": 10,
            "currency": "EUR",
        },
    ).json()
    resp = client.post(
        f"/api/v1/trades/{trade['id']}/costs",
        json={"cost_type": "commission", "amount": 2.5, "currency": "EUR"},
    )
    assert resp.status_code == 201
    costs = client.get(f"/api/v1/trades/{trade['id']}/costs").json()
    assert len(costs) == 1


def test_price_import_handles_utf8_bom(client):
    """Reproduce a file generated by PowerShell Out-File -Encoding utf8, which writes a UTF-8 BOM at the beginning."""
    _make_security(client)
    csv_content = (
        "date;ticker;close\n"
        "2026-07-10;ENI.MI;17,00\n"  # comma decimals
    )
    # encode(utf-8-sig) automatically prefixes a UTF-8 BOM
    file = io.BytesIO(csv_content.encode("utf-8-sig"))
    resp = client.post(
        "/api/v1/prices/import", files={"file": ("prices_bom.csv", file, "text/csv")}
    )
    assert resp.status_code == 200
    assert resp.json() == {
        "imported": 1,
        "updated": 0,
        "skipped_unrecognized_ticker": 0,
        "errors": 0,
    }


def test_price_import_preview_flags_new_and_update_rows_without_writing(client):
    """Preview (dry run) distinguishes new rows from updates and writes nothing: a second GET latest must still fail until the actual import is confirmed (§8.1)."""
    sec_id = _make_security(client)
    client.post(
        "/api/v1/prices",
        json={"security_id": sec_id, "date": "2026-07-10", "price_close": "17.00"},
    )

    csv_content = (
        "date;ticker;close\n"
        "2026-07-10;ENI.MI;17,50\n"  # existing date -> update
        "2026-07-15;ENI.MI;18.00\n"  # new date -> new
    )
    file = io.BytesIO(csv_content.encode("utf-8"))
    resp = client.post(
        "/api/v1/prices/import/preview", files={"file": ("prices.csv", file, "text/csv")}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_rows"] == 2
    assert body["new_rows"] == 1
    assert body["update_rows"] == 1
    assert body["skipped_unrecognized_ticker"] == 0
    assert body["error_rows"] == 0
    assert body["rows"][0]["is_update"] is True
    assert body["rows"][1]["is_update"] is False

    # dry run: the 2026-07-10 price must not have been overwritten
    latest = client.get(f"/api/v1/prices/{sec_id}/latest").json()
    assert latest["date"] == "2026-07-10"
    assert float(latest["price_close"]) == 17.00
    history = client.get(f"/api/v1/prices/{sec_id}").json()
    assert len(history) == 1


def test_price_import_preview_flags_unrecognized_ticker_and_errors(client):
    _make_security(client)
    csv_content = "date;ticker;close\n" "2026-07-10;SCONOSCIUTO;17.00\n" "not-a-date;ENI.MI;abc\n"
    file = io.BytesIO(csv_content.encode("utf-8"))
    resp = client.post(
        "/api/v1/prices/import/preview", files={"file": ("prices.csv", file, "text/csv")}
    )
    body = resp.json()
    assert body["total_rows"] == 2
    assert body["skipped_unrecognized_ticker"] == 1
    assert body["error_rows"] == 1
    assert body["rows"][0]["security_id"] is None
    assert body["rows"][1]["errors"] != []


def test_trade_records_its_price_in_history(client):
    """A trade is an observed market price: recording it adds a historical price if none exists for that date."""
    sec_id = _make_security(client)
    acc_id = _make_account(client)
    client.post(
        "/api/v1/trades",
        json={
            "security_id": sec_id,
            "account_id": acc_id,
            "type": "buy",
            "date": "2026-03-05",
            "quantity": 10,
            "price": 14.5,
            "currency": "EUR",
        },
    )

    history = client.get(f"/api/v1/prices/{sec_id}").json()
    assert len(history) == 1
    assert history[0]["date"] == "2026-03-05"
    assert float(history[0]["price_close"]) == 14.5
    assert history[0]["source"] == "trade"


def test_latest_prices_returns_all_securities_in_one_request(client):
    first = _make_security(client, ticker="ONE.MI")
    second = _make_security(client, ticker="TWO.MI")
    for security_id, value in ((first, "10"), (second, "20")):
        response = client.post(
            "/api/v1/prices",
            json={
                "security_id": security_id,
                "date": "2026-08-01",
                "price_close": value,
            },
        )
        assert response.status_code == 201

    response = client.get("/api/v1/prices/latest")
    assert response.status_code == 200
    assert [row["security_id"] for row in response.json()] == sorted((first, second))


def test_latest_prices_ignore_future_rows_but_history_keeps_them(client):
    today = dt.date.today()
    future = today + dt.timedelta(days=1)
    current_security = _make_security(client, ticker="CURRENT.MI")
    future_only_security = _make_security(client, ticker="FUTURE.MI")

    for security_id, date, value in (
        (current_security, today, "10"),
        (current_security, future, "999"),
        (future_only_security, future, "777"),
    ):
        response = client.post(
            "/api/v1/prices",
            json={
                "security_id": security_id,
                "date": date.isoformat(),
                "price_close": value,
            },
        )
        assert response.status_code == 201

    latest = client.get("/api/v1/prices/latest")
    assert latest.status_code == 200
    assert [(row["security_id"], row["date"]) for row in latest.json()] == [
        (current_security, today.isoformat())
    ]

    individual = client.get(f"/api/v1/prices/{current_security}/latest")
    assert individual.status_code == 200
    assert individual.json()["date"] == today.isoformat()
    assert float(individual.json()["price_close"]) == 10.0

    assert client.get(f"/api/v1/prices/{future_only_security}/latest").status_code == 404
    history = client.get(f"/api/v1/prices/{future_only_security}")
    assert history.status_code == 200
    assert [row["date"] for row in history.json()] == [future.isoformat()]


def test_trade_price_never_overwrites_an_existing_price(client):
    """An imported or manually entered closing price is the official market value: a single execution price must not replace it."""
    sec_id = _make_security(client)
    acc_id = _make_account(client)
    client.post(
        "/api/v1/prices",
        json={"security_id": sec_id, "date": "2026-03-05", "price_close": "15.00"},
    )

    client.post(
        "/api/v1/trades",
        json={
            "security_id": sec_id,
            "account_id": acc_id,
            "type": "buy",
            "date": "2026-03-05",
            "quantity": 10,
            "price": 14.5,
            "currency": "EUR",
        },
    )

    history = client.get(f"/api/v1/prices/{sec_id}").json()
    assert len(history) == 1
    assert float(history[0]["price_close"]) == 15.00
    assert history[0]["source"] == "manual"


def test_sale_price_keeps_portfolio_valuation_coherent(client):
    """Recording the sale price prevents valuation on that date from falling below proceeds, the inconsistency that made TWR unavailable (§9.3)."""
    sec_id = _make_security(client)
    acc_id = _make_account(client)
    client.post(
        "/api/v1/trades",
        json={
            "security_id": sec_id,
            "account_id": acc_id,
            "type": "buy",
            "date": "2026-01-10",
            "quantity": 100,
            "price": 10,
            "currency": "EUR",
        },
    )
    client.post(
        "/api/v1/trades",
        json={
            "security_id": sec_id,
            "account_id": acc_id,
            "type": "sell",
            "date": "2026-06-10",
            "quantity": 50,
            "price": 18,
            "currency": "EUR",
        },
    )

    history = {
        p["date"]: float(p["price_close"]) for p in client.get(f"/api/v1/prices/{sec_id}").json()
    }
    assert history["2026-01-10"] == 10.0
    assert history["2026-06-10"] == 18.0

    body = client.get("/api/v1/performance/portfolio").json()
    assert body["time_weighted_return"] is not None
