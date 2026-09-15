"""Internal reports must not silently truncate at 100,000 rows."""

import datetime as dt
from decimal import Decimal
from itertools import repeat
from types import SimpleNamespace
from unittest.mock import Mock

from app.finance.statistics import winsorized_mean
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
    return service


def test_income_statement_and_average_expenses_include_rows_beyond_legacy_cap():
    service = _service_with_repeated_expense()

    statement = service.income_statement()
    average = service._average_monthly_expenses(dt.date(2026, 1, 31))

    assert statement.total_expense == Decimal(-ROW_COUNT_OVER_LEGACY_CAP)
    assert average == winsorized_mean([Decimal(ROW_COUNT_OVER_LEGACY_CAP), *([Decimal("0")] * 11)])


def test_category_analysis_includes_rows_beyond_legacy_cap():
    service = _service_with_repeated_expense()

    report = service.spending_analysis()

    assert report.total_amount == Decimal(-ROW_COUNT_OVER_LEGACY_CAP)
    assert report.by_category[0].category_name == "Uncategorized"
    assert report.by_category[0].total_amount == Decimal(-ROW_COUNT_OVER_LEGACY_CAP)
    assert report.by_top_level_category == report.by_category
