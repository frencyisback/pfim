"""Unit tests for app.finance.forecast.
See technical-specification.md §10.
"""

import datetime as dt
from decimal import Decimal

import pytest

from app.finance.forecast import run_forecast_scenario


def _base_params(**overrides):
    params = dict(
        horizon_years=3,
        base_date=dt.date(2026, 1, 1),
        starting_cash_balance=Decimal("5000"),
        starting_portfolio_value=Decimal("10000"),
        monthly_income=Decimal("3000"),
        monthly_expenses=Decimal("2000"),
        income_growth_rate_annual=Decimal("0"),
        expense_growth_rate_annual=Decimal("0"),
        expected_annual_return=Decimal("0.07"),
        return_optimistic=Decimal("0.10"),
        return_pessimistic=Decimal("0.04"),
        monthly_savings_to_invest=None,
        contributions=[],
    )
    params.update(overrides)
    return params


def test_three_scenarios_produced():
    result = run_forecast_scenario(_base_params())
    assert set(result.scenarios.keys()) == {"pessimistic", "base", "optimistic"}
    for scenario in result.scenarios.values():
        assert len(scenario.years) == 3


def test_base_scenario_year_one_calculation():
    """Year 1: annual savings = (3000-2000)*12 = 12000, fully invested.
    Portfolio: 10000*1.07 + 12000 = 22700
    Cash: unchanged (the entire 12000 flow is invested) = 5000
    Net worth: 27700
    """
    result = run_forecast_scenario(_base_params())
    year1 = result.scenarios["base"].years[0]
    assert year1.portfolio_value == Decimal("22700")
    assert year1.cash_balance == Decimal("5000")
    assert year1.net_worth == Decimal("27700")


def test_optimistic_greater_than_pessimistic():
    result = run_forecast_scenario(_base_params())
    base_final = result.scenarios["base"].years[-1].net_worth
    opt_final = result.scenarios["optimistic"].years[-1].net_worth
    pess_final = result.scenarios["pessimistic"].years[-1].net_worth
    assert pess_final < base_final < opt_final


def test_negative_cash_flow_reduces_cash_not_portfolio():
    """When expenses exceed income, the deficit reduces cash, not the portfolio."""
    params = _base_params(monthly_income=Decimal("1000"), monthly_expenses=Decimal("2000"))
    result = run_forecast_scenario(params)
    year1 = result.scenarios["base"].years[0]
    # Annual deficit: (1000-2000)*12 = -12000
    assert year1.cash_balance == Decimal("5000") - Decimal("12000")
    # Portfolio grows ONLY through returns, with no contribution (deficit, not invested)
    assert year1.portfolio_value == Decimal("10000") * Decimal("1.07")


def test_extraordinary_contribution_applied_in_correct_year():
    params = _base_params(
        horizon_years=2,
        contributions=[
            (dt.date(2027, 6, 1), Decimal("20000"))
        ],  # second interval: (2027-01-01, 2028-01-01]
    )
    result = run_forecast_scenario(params)
    year1 = result.scenarios["base"].years[0]
    year2 = result.scenarios["base"].years[1]
    year1_without_contribution = Decimal("10000") * Decimal("1.07") + Decimal("12000")
    assert year1.portfolio_value == year1_without_contribution
    assert year2.portfolio_value == year1.portfolio_value * Decimal("1.07") + Decimal("32000")


@pytest.mark.parametrize("scenario_name", ["pessimistic", "base", "optimistic"])
def test_contributions_follow_anniversary_intervals_and_are_added_at_period_end(scenario_name):
    params = _base_params(
        base_date=dt.date(2026, 6, 1),
        horizon_years=2,
        monthly_income=Decimal("0"),
        monthly_expenses=Decimal("0"),
        contributions=[
            (dt.date(2026, 5, 31), Decimal("999999")),  # before the base date
            (dt.date(2026, 6, 1), Decimal("999999")),  # already included in starting net worth
            (dt.date(2026, 6, 2), Decimal("100")),
            (dt.date(2026, 9, 1), Decimal("20")),
            (dt.date(2027, 6, 1), Decimal("-30")),  # inclusive endpoint
            (dt.date(2027, 6, 2), Decimal("200")),
            (dt.date(2028, 6, 1), Decimal("-50")),
            (dt.date(2028, 6, 2), Decimal("999999")),  # beyond the horizon
        ],
    )
    years = run_forecast_scenario(params).scenarios[scenario_name].years
    rate = {"pessimistic": Decimal(".04"), "base": Decimal(".07"), "optimistic": Decimal(".10")}
    assert years[0].portfolio_value == Decimal("10000") * (1 + rate[scenario_name]) + 90
    assert years[1].portfolio_value == years[0].portfolio_value * (1 + rate[scenario_name]) + 150
    assert all(year.cash_balance == Decimal("5000") for year in years)


@pytest.mark.parametrize("day", [29, 30, 31])
def test_anniversaries_preserve_regular_month_days(day):
    params = _base_params(base_date=dt.date(2026, 5, day))
    for scenario in run_forecast_scenario(params).scenarios.values():
        assert [year.date for year in scenario.years] == [
            dt.date(y, 5, day) for y in range(2027, 2030)
        ]


def test_leap_anniversaries_return_to_february_29_and_preserve_interval_boundaries():
    params = _base_params(
        base_date=dt.date(2024, 2, 29),
        horizon_years=4,
        starting_portfolio_value=Decimal("0"),
        monthly_income=Decimal("0"),
        monthly_expenses=Decimal("0"),
        contributions=[
            (dt.date(2025, 2, 28), Decimal("10")),
            (dt.date(2025, 3, 1), Decimal("20")),
            (dt.date(2028, 2, 29), Decimal("30")),
            (dt.date(2028, 3, 1), Decimal("999999")),
        ],
    )
    for name, scenario in run_forecast_scenario(params).scenarios.items():
        assert [year.date for year in scenario.years] == [
            dt.date(2025, 2, 28),
            dt.date(2026, 2, 28),
            dt.date(2027, 2, 28),
            dt.date(2028, 2, 29),
        ]
        rate = {
            "pessimistic": Decimal(".04"),
            "base": Decimal(".07"),
            "optimistic": Decimal(".10"),
        }[name]
        assert scenario.years[0].portfolio_value == 10
        assert scenario.years[1].portfolio_value == 10 * (1 + rate) + 20
        assert scenario.years[3].portfolio_value == (10 * (1 + rate) + 20) * (1 + rate) ** 2 + 30


def test_monthly_savings_override_used_instead_of_auto():
    """Explicit user-defined savings are invested regardless of actual cash flow, which is consumed or accumulated in cash."""
    params = _base_params(
        monthly_savings_to_invest=Decimal("500")
    )  # instead of automatic 1000/month
    result = run_forecast_scenario(params)
    year1 = result.scenarios["base"].years[0]
    invested = Decimal("500") * 12
    assert year1.portfolio_value == Decimal("10000") * Decimal("1.07") + invested
    # Automatic cash flow would be 12000; only 6000 invested; the remaining 6000 goes to cash
    assert year1.cash_balance == Decimal("5000") + (Decimal("12000") - invested)


def test_milestones_detected_at_correct_year():
    params = _base_params(
        horizon_years=10,
        milestones=[Decimal("50000")],
    )
    result = run_forecast_scenario(params)
    base_scenario = result.scenarios["base"]
    assert "50000" in base_scenario.milestones_reached
    reached_year = base_scenario.milestones_reached["50000"]
    # Verify the reported year is the first when the threshold is exceeded
    assert base_scenario.years[reached_year - 1].net_worth >= Decimal("50000")
    if reached_year > 1:
        assert base_scenario.years[reached_year - 2].net_worth < Decimal("50000")


def test_income_and_expense_growth_compounds_year_over_year():
    params = _base_params(
        horizon_years=2,
        income_growth_rate_annual=Decimal("0.10"),
        expense_growth_rate_annual=Decimal("0"),
    )
    result = run_forecast_scenario(params)
    year1 = result.scenarios["base"].years[0]
    year2 = result.scenarios["base"].years[1]
    assert year1.annual_income == Decimal("3000") * 12
    # year 2: monthly income increased by 10% over year 1
    assert year2.annual_income == Decimal("3000") * Decimal("1.10") * 12
