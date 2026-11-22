"""Internal reports must not silently truncate at 100,000 rows."""

import datetime as dt
from decimal import Decimal
from itertools import repeat
from types import SimpleNamespace
from unittest.mock import Mock

from app.services.report_service import ReportService

ROW_COUNT_OVER_LEGACY_CAP = 100_001


def _service_with_repeated_expense():
    transaction = SimpleNamespace(
        id=1,
        date=dt.date(2026, 1, 15),
        amount=Decimal(-1),
        currency="EUR",
        amount_eur=Decimal(-1),
        category_id=None,
        description="Expense",
        transfer_group_id=None,
        trade_id=None,
        income_event_id=None,
        portfolio_cost_id=None,
    )
    service = ReportService.__new__(ReportService)
    service.transaction_repo = Mock()
    service.transaction_repo.iter_filtered.side_effect = lambda **_: repeat(
        transaction, ROW_COUNT_OVER_LEGACY_CAP
    )
    service.transaction_repo.list.side_effect = AssertionError(
        "complete reports must not return to capped pagination"
    )
    service._categories_cache = {}
    service.db = Mock()
    service.db.execute.return_value = []
    service.income_event_repo = Mock()
    service.income_event_repo.list.return_value = []
    service.portfolio_cost_repo = Mock()
    service.portfolio_cost_repo.list.return_value = []
    return service


def test_income_statement_and_average_expenses_include_rows_beyond_legacy_cap():
    service = _service_with_repeated_expense()

    statement = service.income_statement()
    average, coverage = service._spending_history(dt.date(2026, 1, 31))

    assert statement.total_expense == Decimal(-ROW_COUNT_OVER_LEGACY_CAP)
    assert statement.economic_savings == -ROW_COUNT_OVER_LEGACY_CAP
    assert average == ROW_COUNT_OVER_LEGACY_CAP
    assert coverage.months_with_recorded_expenses == 1


def test_category_analysis_includes_rows_beyond_legacy_cap():
    service = _service_with_repeated_expense()

    report = service.spending_analysis()

    assert report.total_amount == Decimal(-ROW_COUNT_OVER_LEGACY_CAP)
    assert report.by_category[0].category_name == "Uncategorized"
    assert report.by_category[0].total_amount == Decimal(-ROW_COUNT_OVER_LEGACY_CAP)
    assert report.by_top_level_category == report.by_category
