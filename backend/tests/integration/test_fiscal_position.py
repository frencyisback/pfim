"""Capital losses offset capital gains, with a single calculation.

Previously, capital-gains tax was calculated in THREE places: TaxService
stored 26% of each individual gain on its event, costs-analysis summed
those values, and tax-register recalculated tax on the offset net amount.
A gain of 1,000 and a loss of 600 therefore showed 260 in one report and
104 in another.

ReportService.fiscal_position is now the single source.
"""

from decimal import Decimal


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


def _security(client, ticker):
    return client.post(
        "/api/v1/securities",
        json={"ticker": ticker, "name": ticker, "type": "stock", "currency": "EUR"},
    ).json()["id"]


def _round_trip(client, dep, ticker, buy_price, sell_price, quantity=10):
    """Buy and resell, generating the corresponding capital gain or loss."""
    sec = _security(client, ticker)
    client.post(
        "/api/v1/trades",
        json={
            "security_id": sec,
            "account_id": dep,
            "type": "buy",
            "date": "2026-01-10",
            "quantity": quantity,
            "price": buy_price,
            "currency": "EUR",
        },
    )
    return client.post(
        "/api/v1/trades",
        json={
            "security_id": sec,
            "account_id": dep,
            "type": "sell",
            "date": "2026-06-10",
            "quantity": quantity,
            "price": sell_price,
            "currency": "EUR",
        },
    ).json()


def _fiscal(client, **params):
    return client.get("/api/v1/reports/costs-analysis", params=params).json()["fiscal"]


class TestCompensation:
    def test_losses_offset_gains(self, client):
        """The previously inconsistent case: +1,000 and -600 at 26%."""
        _, dep = _accounts(client)
        _round_trip(client, dep, "GAIN", buy_price=100, sell_price=200)  # +1000
        _round_trip(client, dep, "LOSS", buy_price=100, sell_price=40)  # -600

        fiscal = _fiscal(client)

        assert Decimal(fiscal["capital_gains"]) == 1000
        assert Decimal(fiscal["capital_losses"]) == -600
        assert Decimal(fiscal["net_capital_gain_loss"]) == 400
        # 26% of 400, not 1,000
        assert Decimal(fiscal["gross_estimated_tax"]) == Decimal("104.00")
        assert Decimal(fiscal["estimated_tax_due"]) == Decimal("104.00")

    def test_a_losing_period_owes_nothing(self, client):
        """Negative net amount: no tax, rather than negative tax."""
        _, dep = _accounts(client)
        _round_trip(client, dep, "GAIN", buy_price=100, sell_price=120)  # +200
        _round_trip(client, dep, "LOSS", buy_price=100, sell_price=40)  # -600

        fiscal = _fiscal(client)

        assert Decimal(fiscal["net_capital_gain_loss"]) == -400
        assert Decimal(fiscal["gross_estimated_tax"]) == 0
        assert Decimal(fiscal["estimated_tax_due"]) == 0

    def test_gains_alone_are_taxed_in_full(self, client):
        """Without capital losses, offsetting changes nothing."""
        _, dep = _accounts(client)
        _round_trip(client, dep, "GAIN", buy_price=100, sell_price=200)  # +1000

        fiscal = _fiscal(client)
        assert Decimal(fiscal["estimated_tax_due"]) == Decimal("260.00")

    def test_compensation_is_limited_to_the_period(self, client):
        """A loss in one year does not offset a gain in another: v1.0 does not carry losses forward."""
        _, dep = _accounts(client)
        sec = _security(client, "AAA")
        client.post(
            "/api/v1/trades",
            json={
                "security_id": sec,
                "account_id": dep,
                "type": "buy",
                "date": "2025-01-10",
                "quantity": 10,
                "price": 100,
                "currency": "EUR",
            },
        )
        client.post(  # capital loss in 2025
            "/api/v1/trades",
            json={
                "security_id": sec,
                "account_id": dep,
                "type": "sell",
                "date": "2025-06-10",
                "quantity": 10,
                "price": 40,
                "currency": "EUR",
            },
        )
        _round_trip(client, dep, "BBB", buy_price=100, sell_price=200)  # +1000 in 2026

        solo_2026 = _fiscal(client, date_from="2026-01-01", date_to="2026-12-31")
        assert Decimal(solo_2026["capital_losses"]) == 0
        assert Decimal(solo_2026["estimated_tax_due"]) == Decimal("260.00")

        both_results = _fiscal(client)
        assert Decimal(both_results["net_capital_gain_loss"]) == 400
        assert Decimal(both_results["estimated_tax_due"]) == Decimal("104.00")


class TestAlreadyWithheld:
    def test_tax_registered_on_a_sale_is_subtracted(self, client):
        """Amounts already withheld by the intermediary must not be counted twice."""
        _, dep = _accounts(client)
        sell = _round_trip(client, dep, "GAIN", buy_price=100, sell_price=200)  # +1000
        client.post(
            f"/api/v1/trades/{sell['id']}/costs",
            json={"cost_type": "tax", "amount": 260, "currency": "EUR"},
        )

        fiscal = _fiscal(client)
        assert Decimal(fiscal["gross_estimated_tax"]) == Decimal("260.00")
        assert Decimal(fiscal["tax_already_withheld"]) == Decimal("260.00")
        assert Decimal(fiscal["estimated_tax_due"]) == 0

    def test_it_never_goes_negative(self, client):
        """If withholding exceeds the estimate, the remainder is zero: tax credits are outside the scope of v1.0."""
        _, dep = _accounts(client)
        sell = _round_trip(client, dep, "GAIN", buy_price=100, sell_price=200)
        client.post(
            f"/api/v1/trades/{sell['id']}/costs",
            json={"cost_type": "tax", "amount": 400, "currency": "EUR"},
        )

        assert Decimal(_fiscal(client)["estimated_tax_due"]) == 0

    def test_stamp_duty_on_a_trade_does_not_reduce_the_estimate(self, client):
        """Stamp duty is a tax on assets: subtracting it from capital-gains tax would reduce the bill for the wrong reason."""
        _, dep = _accounts(client)
        sell = _round_trip(client, dep, "GAIN", buy_price=100, sell_price=200)
        client.post(
            f"/api/v1/trades/{sell['id']}/costs",
            json={"cost_type": "stamp_duty", "amount": 50, "currency": "EUR"},
        )

        fiscal = _fiscal(client)
        assert Decimal(fiscal["tax_already_withheld"]) == 0
        assert Decimal(fiscal["estimated_tax_due"]) == Decimal("260.00")

    def test_a_tax_on_a_purchase_is_not_a_capital_gains_tax(self, client):
        """Purchases do not incur capital-gains tax."""
        _, dep = _accounts(client)
        sec = _security(client, "AAA")
        buy = client.post(
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
            f"/api/v1/trades/{buy['id']}/costs",
            json={"cost_type": "tax", "amount": 5, "currency": "EUR"},
        )

        assert Decimal(_fiscal(client)["tax_already_withheld"]) == 0


class TestSingleSourceOfTruth:
    def test_the_cost_item_matches_the_fiscal_position(self, client):
        """The cost entry and tax section must show the same number: exactly the inconsistency this work removes."""
        _, dep = _accounts(client)
        _round_trip(client, dep, "GAIN", buy_price=100, sell_price=200)
        _round_trip(client, dep, "LOSS", buy_price=100, sell_price=40)

        body = client.get("/api/v1/reports/costs-analysis").json()
        estimated_items = [
            i
            for g in body["groups"]
            for i in g["items"]
            if i["cost_type"] == "capital_gains_tax" and i["is_estimated"]
        ]

        assert len(estimated_items) == 1, "one entry on the net amount, not one per capital gain"
        assert Decimal(estimated_items[0]["amount_eur"]) == Decimal(
            body["fiscal"]["estimated_tax_due"]
        )

    def test_the_estimate_explains_the_compensation(self, client):
        """An unexplained total creates uncertainty: its description must show the calculation."""
        _, dep = _accounts(client)
        _round_trip(client, dep, "GAIN", buy_price=100, sell_price=200)
        _round_trip(client, dep, "LOSS", buy_price=100, sell_price=40)

        body = client.get("/api/v1/reports/costs-analysis").json()
        item = next(
            i
            for g in body["groups"]
            for i in g["items"]
            if i["cost_type"] == "capital_gains_tax" and i["is_estimated"]
        )
        assert "offset by" in item["description"]

    def test_per_event_tax_is_not_summed_into_the_total(self, client):
        """Event tax_amount remains a detail (gross tax on the individual gain) but must no longer feed any total."""
        _, dep = _accounts(client)
        _round_trip(client, dep, "GAIN", buy_price=100, sell_price=200)
        _round_trip(client, dep, "LOSS", buy_price=100, sell_price=40)

        events = client.get("/api/v1/tax-events").json()
        gain_event = next(e for e in events if e["event_type"] == "capital_gain")
        assert Decimal(gain_event["tax_amount"]) == Decimal("260.00")  # gross, before offsetting

        taxes = next(
            g
            for g in client.get("/api/v1/reports/costs-analysis").json()["groups"]
            if g["group"] == "taxes"
        )
        assert Decimal(taxes["total_eur"]) == Decimal("104.00")  # after offsetting


class TestRemovedReport:
    def test_tax_register_report_is_gone(self, client):
        """The accountant document was removed: its aggregates now live in costs-analysis without duplication."""
        assert client.get("/api/v1/reports/tax-register").status_code == 404

    def test_manual_tax_events_still_work(self, client):
        """Manual tax entries (§11.1) remain supported for information the system cannot infer; without them, offsetting would use only automatic data."""
        _, dep = _accounts(client)
        _round_trip(client, dep, "GAIN", buy_price=100, sell_price=200)  # +1000

        client.post(
            "/api/v1/tax-events",
            json={
                "event_date": "2026-03-01",
                "event_type": "capital_loss",
                "description": "Previous capital loss",
                "gross_amount": -500,
            },
        )

        fiscal = _fiscal(client)
        assert Decimal(fiscal["capital_losses"]) == -500
        assert Decimal(fiscal["estimated_tax_due"]) == Decimal("130.00")  # 26% of 500
