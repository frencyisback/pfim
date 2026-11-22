"""Public performance endpoints must use the same holdings as their denominators."""

import datetime as dt
from decimal import Decimal

from sqlalchemy import delete

from app.models.price import Price

from .conftest import TestingSessionLocal
from .test_dividends_analysis import _make_accounts, _make_security


def _day(ago):
    return (dt.date.today() - dt.timedelta(days=ago)).isoformat()


def _trade(client, account, security, kind, ago, quantity, price=10):
    response = client.post(
        "/api/v1/trades",
        json=dict(
            account_id=account,
            security_id=security,
            type=kind,
            date=_day(ago),
            quantity=quantity,
            price=price,
            currency="EUR",
        ),
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _payment(client, account, security, ago, amount, *, kind="dividend", ex_ago=None, tax=0):
    response = client.post(
        "/api/v1/income-events",
        json=dict(
            account_id=account,
            security_id=security,
            event_type=kind,
            payment_date=_day(ago),
            ex_date=_day(ex_ago) if ex_ago is not None else None,
            total_amount=amount,
            currency="EUR",
            tax_withheld=tax,
        ),
    )
    assert response.status_code == 201, response.text


def _performance(client, security="portfolio", include_costs=False, income_basis="net"):
    response = client.get(
        f"/api/v1/performance/{security}",
        params={
            "cost_basis": "include" if include_costs else "exclude",
            "income_basis": income_basis,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_partial_sale_attributes_only_income_and_acquisition_cost_of_remaining_units(client):
    account = _make_accounts(client)
    sec = _make_security(client, "PART")
    buy = _trade(client, account, sec, "buy", 300, 100)
    _payment(client, account, sec, 250, 50)
    sell = _trade(client, account, sec, "sell", 100, 90)
    for trade_id, fee in ((buy, 20), (sell, 10)):
        assert (
            client.post(
                f"/api/v1/trades/{trade_id}/costs",
                json={"cost_type": "commission", "amount": fee, "currency": "EUR"},
            ).status_code
            == 201
        )
    # The historical dividend is EUR 50. Ten of the original 100 units survive,
    # carrying EUR 5 of distributions and EUR 2 of acquisition costs.
    for endpoint in (sec, "portfolio"):
        before_costs = _performance(client, endpoint)
        assert Decimal(before_costs["total_income_received"]) == 50
        assert Decimal(before_costs["total_return"]) == Decimal("0.05")
        assert Decimal(_performance(client, endpoint, True)["total_return"]) == Decimal("0.03")
    security = _performance(client, sec)
    assert Decimal(security["yield_on_cost"]) == Decimal(security["current_yield"]) == 5


def test_closed_security_and_reopened_lots_do_not_inherit_past_distributions(client):
    account = _make_accounts(client)
    a = _make_security(client, "CLOSED")
    b = _make_security(client, "NEW")
    _trade(client, account, a, "buy", 800, 100)
    _trade(client, account, a, "sell", 400, 100)
    _trade(client, account, b, "buy", 365, 1)
    _payment(client, account, a, 300, 100, ex_ago=450)
    assert _performance(client, a)["total_return"] is None
    summary = _performance(client)
    assert Decimal(summary["total_income_received"]) == 100
    assert Decimal(summary["total_return"]) == Decimal(summary["total_return_annualized"]) == 0
    _trade(client, account, a, "buy", 200, 10)
    # A late payment with ex-date in the old holding period belongs to the old lots.
    _payment(client, account, a, 100, 10, ex_ago=450)
    assert Decimal(_performance(client, a)["total_return"]) == 0
    summary = _performance(client)
    assert Decimal(summary["total_return"]) == 0
    assert Decimal(summary["total_return_annualized"]) == 0  # Two ages and no gain.
    assert summary["total_return_annualized_unavailable_reason"] is None


def test_annualized_open_lot_return_uses_residual_costs_and_selected_distribution_basis(client):
    account = _make_accounts(client)
    sec = _make_security(client, "VINTAGES")
    oldest = _trade(client, account, sec, "buy", 730, 20)
    _payment(client, account, sec, 500, 80, tax=18)
    _trade(client, account, sec, "buy", 365, 10)
    _trade(client, account, sec, "sell", 100, 10)
    assert (
        client.post(
            f"/api/v1/trades/{oldest}/costs",
            json={
                "cost_type": "commission",
                "amount": 20,
                "currency": "EUR",
            },
        ).status_code
        == 201
    )
    # Ten units of each EUR 100 lot remain. Half the EUR 80 gross dividend
    # (EUR 62 net) and half the original EUR 20 purchase fee are attributable.
    for basis, costs, terminal in (
        ("net", False, 231),
        ("gross", False, 240),
        ("net", True, 221),
        ("gross", True, 230),
    ):
        summary = _performance(client, include_costs=costs, income_basis=basis)
        assert summary["total_return_annualized_unavailable_reason"] is None
        rate = Decimal(summary["total_return_annualized"])
        assert abs(100 * (1 + rate) ** 2 + 100 * (1 + rate) - terminal) < Decimal(".00001")
        assert Decimal(summary["total_return"]) == Decimal(terminal) / 200 - 1


def test_annualized_open_lot_unavailable_reasons_follow_actual_holdings(client):
    def unavailable(reason, *, include_costs=False):
        result = _performance(client, include_costs=include_costs)
        assert result["total_return_annualized"] is None
        assert result["total_return_annualized_unavailable_reason"] == reason
        return result

    account = _make_accounts(client)
    sec = _make_security(client, "OPENREASON")
    unavailable("no_open_cost")
    _trade(client, account, sec, "buy", 0, 10)
    unavailable("no_elapsed_days")
    old = _trade(client, account, sec, "buy", 365, 10)
    # Same-day capital still contributes EUR 100 at terminal time. With
    # EUR 100 of fees the remaining EUR 100 cannot fund a finite rate above -100%.
    assert (
        client.post(
            f"/api/v1/trades/{old}/costs",
            json={
                "cost_type": "commission",
                "amount": 100,
                "currency": "EUR",
            },
        ).status_code
        == 201
    )
    unavailable("undefined_rate", include_costs=True)
    assert Decimal(_performance(client)["total_return_annualized"]) == 0
    with TestingSessionLocal.begin() as db:
        db.execute(delete(Price).where(Price.security_id == sec))
    result = unavailable("missing_quote")
    assert Decimal(result["total_current_value"]) == 200
    assert result["portfolio_valuation"]["cost_fallback_used"] is True


def test_unfunded_security_affects_neither_traded_holdings_income_nor_returns(client):
    account = _make_accounts(client)
    a = _make_security(client, "FUNDED")
    b = _make_security(client, "UNFUNDED")
    _trade(client, account, a, "buy", 365, 10)
    before = _performance(client)
    _payment(client, account, b, 0, 10)
    assert _performance(client) == before
    assert Decimal(before["time_weighted_return"]) == 0


def test_returned_principal_is_a_cash_flow_and_distribution_but_has_no_income_yield(client):
    account = _make_accounts(client)
    sec = _make_security(client, "PRINCIPAL")
    _trade(client, account, sec, "buy", 365, 10)
    _payment(client, account, sec, 0, 10, kind="return_of_capital")
    assert (
        client.post(
            "/api/v1/prices", json={"security_id": sec, "date": _day(0), "price_close": 9}
        ).status_code
        == 201
    )
    for endpoint in (sec, "portfolio"):
        metrics = _performance(client, endpoint)
        assert Decimal(metrics["total_income_received"]) == 0
        assert Decimal(metrics["total_return"]) == 0
        assert abs(Decimal(metrics["money_weighted_return"])) < Decimal("0.000001")
    assert Decimal(_performance(client, sec)["yield_on_cost"]) == 0
    assert Decimal(_performance(client, sec)["current_yield"]) == 0
    assert Decimal(_performance(client)["time_weighted_return"]) == 0


def test_open_security_without_terminal_quote_cannot_report_partial_xirr(client):
    account = _make_accounts(client)
    sec = _make_security(client, "NOQUOTE")
    _trade(client, account, sec, "buy", 365, 10)
    _payment(client, account, sec, 0, 10)
    # Reproduce a legacy position without a quote, even though an opposing dated
    # distribution alone would give the root finder a mathematically valid IRR.
    with TestingSessionLocal.begin() as db:
        db.execute(delete(Price).where(Price.security_id == sec))
    assert _performance(client, sec)["money_weighted_return"] is None
    _trade(client, account, sec, "sell", 0, 10)
    with TestingSessionLocal.begin() as db:
        db.execute(delete(Price).where(Price.security_id == sec))
    assert abs(
        Decimal(_performance(client, sec)["money_weighted_return"]) - Decimal(".1")
    ) < Decimal(".000001")
