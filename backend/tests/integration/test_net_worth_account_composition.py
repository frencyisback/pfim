"""Account allocation reconciles to point-in-time net worth without changing global FIFO."""

import csv
import datetime as dt
import io
from decimal import ROUND_HALF_UP, Decimal

import pytest
from sqlalchemy import delete, event

from app.models.account import Account
from app.models.price import Price
from app.models.trade import Trade
from app.models.transaction import Transaction

from .conftest import TestingSessionLocal, engine

DAY = "2024-01-31"
CENT = Decimal("0.01")


def _post(client, endpoint, payload):
    response = client.post(f"/api/v1/{endpoint}", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _account(client, name, *, kind="checking", reference=None, opening=0):
    payload = {
        "name": name,
        "type": kind,
        "opened_on": "2000-01-01",
        "opening_balance": opening,
    }
    if reference is not None:
        payload["reference_account_id"] = reference
    return _post(client, "accounts", payload)["id"]


def _security(client, ticker, currency="EUR"):
    return _post(
        client,
        "securities",
        {
            "ticker": ticker,
            "name": f"Security {ticker}",
            "type": "stock",
            "currency": currency,
        },
    )["id"]


def _trade(client, account, security, quantity, price, *, day="2024-01-01", kind="buy", **extra):
    return _post(
        client,
        "trades",
        {
            "account_id": account,
            "security_id": security,
            "quantity": str(quantity),
            "price": str(price),
            "date": day,
            "type": kind,
            "currency": "EUR",
            **extra,
        },
    )["id"]


def _price(client, security, price, *, day=DAY, **extra):
    return _post(
        client,
        "prices",
        {
            "security_id": security,
            "date": day,
            "price_close": str(price),
            **extra,
        },
    )


def _report(client, day=DAY):
    response = client.get("/api/v1/reports/net-worth", params={"as_of_date": day})
    assert response.status_code == 200, response.text
    body = response.json()
    composition = body["account_composition"]
    allocated = sum(
        (
            Decimal(item["value"])
            for item in composition["investment_accounts"]
            if item["value"] is not None
        ),
        Decimal("0"),
    )
    assert allocated + Decimal(composition["unallocated_portfolio_value"]) == Decimal(
        body["total_portfolio_value"]
    ).quantize(CENT, rounding=ROUND_HALF_UP)
    cash = sum((Decimal(item["balance"]) for item in composition["cash_accounts"]), Decimal("0"))
    assert cash + Decimal(composition["unallocated_account_balance"]) == Decimal(
        body["total_accounts_balance"]
    )
    assert Decimal(body["net_worth"]) == (
        Decimal(body["total_accounts_balance"]) + Decimal(body["total_portfolio_value"])
    )
    return body, composition


def _values(composition):
    return {
        item["account_id"]: None if item["value"] is None else Decimal(item["value"])
        for item in composition["investment_accounts"]
    }


def test_two_cash_three_investment_accounts_include_empty_and_share_cash_once(client):
    cash = _account(client, "Current", opening=5000)
    savings = _account(client, "Savings", kind="savings", opening=500)
    first = _account(client, "Broker A", kind="investment", reference=cash)
    second = _account(client, "Broker B", kind="investment", reference=cash)
    empty = _account(client, "Empty broker", kind="investment", reference=cash)
    security = _security(client, "SHARED")
    _trade(client, first, security, 10, 10)
    _trade(client, second, security, 5, 30, day="2024-01-02")
    _trade(client, second, security, 2, 40, day="2024-01-03", kind="sell")
    _price(client, security, 50)
    before = client.get("/api/v1/portfolio").json()
    body, composition = _report(client)
    assert _values(composition) == {first: 500, second: 150, empty: 0}
    assert {
        item["account_id"]: Decimal(item["balance"]) for item in composition["cash_accounts"]
    } == {
        cash: 4830,
        savings: 500,
    }
    assert all(
        item["cost_fallback_securities"] == [] for item in composition["investment_accounts"]
    )
    assert composition["issues"] == []
    assert Decimal(body["total_portfolio_value"]) == 650
    assert Decimal(body["liquid_balance"]) == 4830
    assert len(body["by_account"]) == 5
    assert client.get("/api/v1/portfolio").json() == before
    assert Decimal(before[0]["total_invested_eur"]) == 230
    assert Decimal(before[0]["realized_gain_loss"]) == 60

    exported = client.get("/api/v1/reports/net-worth", params={"as_of_date": DAY, "format": "csv"})
    assert exported.status_code == 200
    parsed = list(csv.DictReader(io.StringIO(exported.text)))
    assert list(parsed[0]) == ["account_id", "name", "balance"]
    assert parsed == [{key: str(value) for key, value in row.items()} for row in body["by_account"]]


def test_multiple_securities_use_quote_currency_fx_and_snapshot_cutoff(client):
    cash = _account(client, "Cash", opening=10000)
    first = _account(client, "A", kind="investment", reference=cash)
    second = _account(client, "B", kind="investment", reference=cash)
    euro = _security(client, "EURO")
    dollar = _security(client, "USD", currency="USD")
    _trade(client, first, euro, 3, 10)
    _trade(client, first, dollar, 2, 40, quote_price="50")
    _trade(client, second, dollar, 5, 40, quote_price="50")
    _price(client, euro, 12)
    _price(client, dollar, 100, fx_rate="0.8")
    _trade(client, first, dollar, 100, 999, day="2024-02-01", quote_price="999")
    _price(client, dollar, 2000, day="2024-02-01", fx_rate="2")
    body, composition = _report(client)
    assert _values(composition) == {first: 196, second: 400}
    assert Decimal(body["total_portfolio_value"]) == 596
    assert Decimal(body["total_accounts_balance"]) == 9690
    assert composition["issues"] == []


def test_missing_quotes_allocate_global_fifo_cost_in_proportion_to_local_quantity(client):
    cash = _account(client, "Cash", opening=1000)
    first = _account(client, "A", kind="investment", reference=cash)
    second = _account(client, "B", kind="investment", reference=cash)
    security = _security(client, "NOQUOTE")
    _trade(client, first, security, 1, 10)
    _trade(client, second, security, 1, 100, day="2024-01-02")
    _trade(client, second, security, ".5", 100, day="2024-01-03", kind="sell")
    with TestingSessionLocal.begin() as session:
        session.execute(delete(Price).where(Price.security_id == security))
    body, composition = _report(client)
    assert Decimal(body["total_portfolio_value"]) == 105
    assert _values(composition) == {first: 70, second: 35}
    for item in composition["investment_accounts"]:
        assert item["cost_fallback_securities"] == [
            {"security_id": security, "ticker": "NOQUOTE", "name": "Security NOQUOTE"}
        ]
    assert body["portfolio_valuation"]["cost_fallback_used"]
    position = client.get(f"/api/v1/portfolio/{security}").json()
    assert Decimal(position["total_invested_eur"]) == 105
    assert Decimal(position["realized_gain_loss"]) == 45
    # A future quote remains unavailable at this cutoff.
    _price(client, security, 1000, day="2024-02-01")
    assert _report(client)[1] == composition
    _price(client, security, 20)
    _, quoted = _report(client)
    assert _values(quoted) == {first: 20, second: 10}
    assert all(not item["cost_fallback_securities"] for item in quoted["investment_accounts"])


@pytest.mark.parametrize(
    "quote,expected_values,expected_total",
    [
        (".005", ["0.00", "0.01", "0.01"], ".02"),
        (".004", ["0.00", "0.00", "0.01"], ".01"),
        (".335", [".33", ".34", ".34"], "1.01"),
    ],
)
def test_fractional_cent_allocations_reconcile_without_changing_raw_portfolio_total(
    client, quote, expected_values, expected_total
):
    cash = _account(client, "Cash")
    empty = _account(client, "AAA empty broker", kind="investment", reference=cash)
    security = _security(client, "FRACTION")
    for index in range(3):
        investment = _account(client, f"Broker {index}", kind="investment", reference=cash)
        _trade(client, investment, security, 1, 1)
    _price(client, security, quote)
    body, composition = _report(client)
    values = _values(composition)
    assert values.pop(empty) == 0
    assert sorted(values.values()) == sorted(map(Decimal, expected_values))
    assert Decimal(body["total_portfolio_value"]) == 3 * Decimal(quote)
    assert sum(_values(composition).values()) == Decimal(expected_total)
    assert Decimal(composition["unallocated_portfolio_value"]) == 0
    assert _report(client)[1] == composition


def test_fifo_cost_split_into_thirds_has_no_spurious_unallocated_cent(client):
    cash = _account(client, "Cash")
    security = _security(client, "THIRDS")
    for index, cost in enumerate([".2", ".3", ".5"]):
        broker = _account(client, f"Broker {index}", kind="investment", reference=cash)
        _trade(client, broker, security, 1, cost)
    with TestingSessionLocal.begin() as session:
        session.execute(delete(Price).where(Price.security_id == security))
    body, composition = _report(client)
    assert Decimal(body["total_portfolio_value"]) == 1
    assert sorted(_values(composition).values()) == list(map(Decimal, [".33", ".33", ".34"]))
    assert Decimal(composition["unallocated_portfolio_value"]) == 0
    assert all(item["cost_fallback_securities"] for item in composition["investment_accounts"])


def test_lifecycle_endpoints_are_inclusive_and_unknown_dates_ignore_active_flag(client):
    cash = _account(client, "Always present", opening=1000)
    dated = _account(client, "Dated cash", opening=25)
    broker = _account(client, "Dated investment", kind="investment", reference=cash)
    legacy = _account(client, "Legacy cash", opening=10)
    unknown_broker = _account(client, "Legacy investment", kind="investment", reference=cash)
    with TestingSessionLocal.begin() as session:
        for ident in (dated, broker):
            record = session.get(Account, ident)
            record.opened_on = dt.date(2024, 1, 10)
            record.closed_on = dt.date(2024, 1, 20)
            record.is_active = False
        for ident in (legacy, unknown_broker):
            record = session.get(Account, ident)
            record.opened_on = record.closed_on = None
            record.is_active = False
    for day, present in [
        ("2024-01-09", False),
        ("2024-01-10", True),
        ("2024-01-20", True),
        ("2024-01-21", False),
    ]:
        body, composition = _report(client, day)
        cash_ids = {row["account_id"] for row in composition["cash_accounts"]}
        investment_ids = set(_values(composition))
        assert (dated in cash_ids) is present
        assert (broker in investment_ids) is present
        assert {cash, legacy} <= cash_ids
        assert unknown_broker in investment_ids
        assert Decimal(body["total_accounts_balance"]) == (1035 if present else 1010)


def test_legacy_local_deficit_hides_all_affected_account_values_and_reconciles_other_holdings(
    client,
):
    cash = _account(client, "Cash")
    first = _account(client, "A", kind="investment", reference=cash)
    second = _account(client, "B", kind="investment", reference=cash)
    valid = _account(client, "C", kind="investment", reference=cash)
    shared = _security(client, "DEFICIT")
    other = _security(client, "OTHER")
    _trade(client, first, shared, 10, 10)
    _trade(client, second, shared, 5, 10)
    sale = _trade(client, first, shared, 8, 20, day="2024-01-15", kind="sell")
    _trade(client, first, other, 2, 50)
    _trade(client, valid, other, 1, 50)
    _price(client, shared, 20, day="2024-01-10")
    with TestingSessionLocal.begin() as session:
        session.get(Trade, sale).account_id = second
    _, before = _report(client, "2024-01-14")
    assert _values(before) == {first: 300, second: 100, valid: 50}
    assert before["issues"] == []
    body, composition = _report(client)
    assert _values(composition) == {first: None, second: None, valid: 50}
    assert Decimal(body["total_portfolio_value"]) == 290
    assert Decimal(composition["unallocated_portfolio_value"]) == 240
    assert composition["issues"] == [
        {
            "account_id": second,
            "name": "B",
            "security_id": shared,
            "ticker": "DEFICIT",
            "reason": "negative_quantity",
        }
    ]


@pytest.mark.parametrize("invalid_kind", ["closed", "not_open_yet", "wrong_type"])
def test_legacy_holdings_outside_visible_investment_accounts_are_explicitly_unallocated(
    client, invalid_kind
):
    cash = _account(client, "Cash", opening=1000)
    broker = _account(client, "Legacy broker", kind="investment", reference=cash)
    security = _security(client, "LEGACY")
    purchase = _trade(client, broker, security, 2, 10)
    _price(client, security, 30)
    with TestingSessionLocal.begin() as session:
        account = session.get(Account, broker)
        if invalid_kind == "closed":
            account.closed_on = dt.date(2024, 1, 15)
            account.is_active = False
        elif invalid_kind == "not_open_yet":
            account.opened_on = dt.date(2024, 2, 1)
        else:
            session.get(Trade, purchase).account_id = cash
    _, composition = _report(client)
    assert Decimal(composition["unallocated_portfolio_value"]) == 60
    assert all(value == 0 for value in _values(composition).values())
    assert composition["issues"] == [
        {
            "account_id": cash if invalid_kind == "wrong_type" else broker,
            "name": "Cash" if invalid_kind == "wrong_type" else "Legacy broker",
            "security_id": security,
            "ticker": "LEGACY",
            "reason": (
                "not_investment_account" if invalid_kind == "wrong_type" else "account_not_present"
            ),
        }
    ]


def test_legacy_investment_cash_is_disclosed_and_cash_decimal_balances_match_existing_endpoint(
    client,
):
    cash = _account(client, "Cash", opening=".01")
    broker = _account(client, "Broker", kind="investment", reference=cash)
    category = _post(client, "categories", {"name": "Income", "type": "income"})["id"]
    for amount in [".1", ".2", ".000001"]:
        _post(
            client,
            "transactions",
            {
                "account_id": cash,
                "category_id": category,
                "date": DAY,
                "amount": amount,
            },
        )
    legacy = _post(
        client,
        "transactions",
        {
            "account_id": cash,
            "category_id": category,
            "date": DAY,
            "amount": "25",
        },
    )["id"]
    with TestingSessionLocal.begin() as session:
        session.get(Transaction, legacy).account_id = broker
    body, composition = _report(client)
    assert Decimal(composition["cash_accounts"][0]["balance"]) == Decimal(".310001")
    assert Decimal(composition["unallocated_account_balance"]) == 25
    assert _values(composition) == {broker: 0}
    for row in body["by_account"]:
        endpoint = client.get(
            f"/api/v1/accounts/{row['account_id']}/balance", params={"as_of_date": DAY}
        )
        assert endpoint.status_code == 200
        assert Decimal(row["balance"]) == Decimal(endpoint.json()["balance"])


def test_empty_dataset_has_no_account_or_portfolio_remainder(client):
    body, composition = _report(client)
    assert body["by_account"] == []
    assert composition == {
        "cash_accounts": [],
        "investment_accounts": [],
        "unallocated_portfolio_value": "0.00",
        "unallocated_account_balance": "0",
        "issues": [],
    }
    assert Decimal(body["net_worth"]) == 0


def test_query_count_is_constant_as_accounts_and_securities_grow(client):
    cash = _account(client, "Reference cash", opening=10000)

    def add(index):
        broker = _account(client, f"Broker {index}", kind="investment", reference=cash)
        security = _security(client, f"SEC{index}")
        _trade(client, broker, security, 1, 10)
        _price(client, security, 20)
        _account(client, f"Cash {index}", opening=100)

    def count():
        queries = []

        def observe(*args):
            queries.append(args[2])

        event.listen(engine, "before_cursor_execute", observe)
        try:
            _report(client)
        finally:
            event.remove(engine, "before_cursor_execute", observe)
        return len(queries)

    add(0)
    small = count()
    for index in range(1, 8):
        add(index)
    large = count()
    assert large == small, f"{small} queries for one holding, {large} for eight"
    assert large <= 20
