"""The tax register follows FIFO, not insertion order.

A sale's realized gain depends on the lots open when it takes place.
Adding a backdated purchase or deleting an earlier sale changes consumed
lots and therefore the taxable amount of ALL subsequent sales.

Previously, the amount was calculated once at sale creation and never
updated. With purchases at different prices, /reports/costs-analysis
reported EUR 600 in capital gains while /portfolio/summary showed EUR 900,
and taxes were calculated from the wrong amount.
"""

from decimal import Decimal


def _accounts(client):
    cash = client.post(
        "/api/v1/accounts",
        json={
            "name": "Checking",
            "type": "checking",
            "opening_balance": 100000,
            "opened_on": "2000-01-01",
        },
    ).json()["id"]
    investment = client.post(
        "/api/v1/accounts",
        json={
            "name": "Investment account",
            "type": "investment",
            "reference_account_id": cash,
            "opened_on": "2000-01-01",
        },
    ).json()["id"]
    return cash, investment


def _security(client, ticker="XXX") -> int:
    return client.post(
        "/api/v1/securities",
        json={"ticker": ticker, "name": ticker, "type": "stock", "currency": "EUR"},
    ).json()["id"]


def _trade(client, security_id, account_id, type_, date, quantity, price):
    resp = client.post(
        "/api/v1/trades",
        json={
            "security_id": security_id,
            "account_id": account_id,
            "type": type_,
            "date": date,
            "quantity": quantity,
            "price": price,
            "currency": "EUR",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _capital_gains(client) -> Decimal:
    """The taxable amount according to the tax register."""
    return Decimal(client.get("/api/v1/reports/costs-analysis").json()["fiscal"]["capital_gains"])


def _realized(client) -> Decimal:
    """The portfolio's realized result, recalculated using FIFO on every read."""
    return Decimal(client.get("/api/v1/portfolio/summary").json()["total_realized_gain_loss"])


def _events(client) -> list:
    return client.get("/api/v1/tax-events").json()


def test_deleting_an_earlier_sell_realigns_the_later_ones(client):
    """Reproduced case: two lots at different prices, two sales.

    Deleting the first sale makes the second consume the older lot instead
    of the newer one, increasing its capital gain from 600 to 900.
    """
    _, investment = _accounts(client)
    security_id = _security(client)
    _trade(client, security_id, investment, "buy", "2026-01-01", 5, 100)
    _trade(client, security_id, investment, "buy", "2026-02-01", 5, 200)
    first_sell = _trade(client, security_id, investment, "sell", "2026-03-01", 5, 300)
    _trade(client, security_id, investment, "sell", "2026-04-01", 3, 400)

    assert _capital_gains(client) == _realized(client) == Decimal("1600")

    assert client.delete(f"/api/v1/trades/{first_sell['id']}").status_code == 204

    # 3 units from the EUR 100 lot: 3 x (400 - 100) = 900
    assert _realized(client) == Decimal("900")
    assert _capital_gains(client) == Decimal("900")
    events = _events(client)
    assert len(events) == 1
    assert Decimal(events[0]["gross_amount"]) == Decimal("900")


def test_a_backdated_buy_realigns_an_existing_sell(client):
    """A purchase recorded today but dated before an existing sale changes the lot consumed by that sale."""
    _, investment = _accounts(client)
    security_id = _security(client)
    _trade(client, security_id, investment, "buy", "2026-02-01", 10, 200)
    _trade(client, security_id, investment, "sell", "2026-03-01", 5, 300)

    assert _capital_gains(client) == Decimal("500")  # 5 x (300 - 200)

    _trade(client, security_id, investment, "buy", "2026-01-01", 5, 100)

    # The sale now consumes the January lot: 5 x (300 - 100) = 1000
    assert _realized(client) == Decimal("1000")
    assert _capital_gains(client) == Decimal("1000")


def test_a_sell_that_becomes_break_even_loses_its_event(client):
    """A break-even sale has no register entry: remove any previous entry created when it consumed a different lot."""
    _, investment = _accounts(client)
    security_id = _security(client)
    cheap = _trade(client, security_id, investment, "buy", "2026-01-01", 5, 100)
    _trade(client, security_id, investment, "buy", "2026-02-01", 5, 300)
    _trade(client, security_id, investment, "sell", "2026-03-01", 5, 300)

    assert len(_events(client)) == 1

    assert client.delete(f"/api/v1/trades/{cheap['id']}").status_code == 204

    # 5 x (300 - 300) = 0: nothing to declare, no entry.
    assert _realized(client) == Decimal("0")
    assert _events(client) == []


def test_a_gain_that_becomes_a_loss_changes_type_and_wording(client):
    """Resynchronization can reverse the sign: type, rate, and automatic description must follow it."""
    _, investment = _accounts(client)
    security_id = _security(client, "ENI")
    cheap = _trade(client, security_id, investment, "buy", "2026-01-01", 5, 100)
    _trade(client, security_id, investment, "buy", "2026-02-01", 5, 500)
    _trade(client, security_id, investment, "sell", "2026-03-01", 5, 300)

    event = _events(client)[0]
    assert event["event_type"] == "capital_gain"
    assert event["description"] == "Capital gain realized on ENI"

    assert client.delete(f"/api/v1/trades/{cheap['id']}").status_code == 204

    event = _events(client)[0]
    assert event["event_type"] == "capital_loss"
    assert Decimal(event["gross_amount"]) == Decimal("-1000")
    assert event["description"] == "Capital loss realized on ENI"
    # Capital losses have no tax to display: they offset gains rather than incur tax.
    assert event["tax_rate"] is None
    assert event["tax_amount"] is None


def test_automatic_tax_is_rounded_explicitly_before_storage(client):
    _, investment = _accounts(client)
    security_id = _security(client, "MICRO")
    _trade(client, security_id, investment, "buy", "2026-01-01", "1", "1")
    _trade(client, security_id, investment, "sell", "2026-02-01", "1", "1.000001")

    event = _events(client)[0]
    assert Decimal(event["gross_amount"]) == Decimal("0.000001")
    # 26% of the micro-gain is 0.00000026: the tax policy rounds to cents
    # with HALF_UP, so zero is intentional and the net uses that exact value.
    assert Decimal(event["tax_amount"]) == Decimal("0.00")
    assert Decimal(event["net_amount"]) == Decimal("0.000001")


def test_fifo_gain_below_persisted_precision_does_not_create_a_zero_event(client):
    _, investment = _accounts(client)
    security_id = _security(client, "SUBMICRO")
    _trade(client, security_id, investment, "buy", "2026-01-01", "0.5", "1")
    _trade(client, security_id, investment, "sell", "2026-02-01", "0.5", "1.000001")

    # 0.5 × 0.000001 = 0.0000005: at NUMERIC(18,6) scale with HALF_EVEN,
    # the taxable amount is zero and must not create a phantom tax entry.
    assert _events(client) == []


def test_automatic_event_rejects_direct_edits_and_survives_realignment(client):
    """Automatic behavior stays stable, but corrections come only from the source."""
    _, investment = _accounts(client)
    security_id = _security(client)
    _trade(client, security_id, investment, "buy", "2026-02-01", 10, 200)
    _trade(client, security_id, investment, "sell", "2026-03-01", 5, 300)

    event_id = _events(client)[0]["id"]
    update = client.put(
        f"/api/v1/tax-events/{event_id}",
        json={
            "description": "Agreed sale adjustment",
            "notes": "Tax reporting note",
            "is_compensated": True,
        },
    )
    assert update.status_code == 409

    _trade(client, security_id, investment, "buy", "2026-01-01", 5, 100)

    event = _events(client)[0]
    assert event["id"] == event_id  # same row, not a new one
    assert event["origin"] == "automatic_trade"
    assert event["description"] == "Capital gain realized on XXX"
    assert event["notes"] is None
    assert event["is_compensated"] is False
    assert Decimal(event["gross_amount"]) == Decimal("1000")


def test_manually_registered_events_are_never_touched(client):
    """Manual user entries are not generated by FIFO: resynchronization must neither change nor delete them."""
    _, investment = _accounts(client)
    security_id = _security(client)
    _trade(client, security_id, investment, "buy", "2026-01-01", 5, 100)

    manual = client.post(
        "/api/v1/tax-events",
        json={
            "event_date": "2026-01-15",
            "event_type": "substitute_tax",
            "description": "Savings account substitute tax",
            "gross_amount": 250,
        },
    ).json()

    _trade(client, security_id, investment, "sell", "2026-03-01", 5, 300)

    still_there = [e for e in _events(client) if e["id"] == manual["id"]]
    assert len(still_there) == 1
    assert still_there[0]["origin"] == "manual"
    assert still_there[0]["description"] == "Savings account substitute tax"
    assert Decimal(still_there[0]["gross_amount"]) == Decimal("250")
