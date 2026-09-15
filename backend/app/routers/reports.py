"""Router: reports."""

from __future__ import annotations

import csv
import datetime as dt
import io

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.report import (
    AccountsBalanceHistoryPoint,
    CategoryAnalysisDetailItem,
    CategoryAnalysisItem,
    CategoryAnalysisReport,
    CostItem,
    CostsAnalysisReport,
    DividendBySecurity,
    DividendsAnalysisReport,
    IncomeStatementPeriod,
    IncomeStatementReport,
    NetWorthReport,
    SecuritiesAnalysisReport,
    SecurityPositionItem,
)
from app.services.report_service import ReportService

router = APIRouter(prefix="/reports", tags=["reports"])


def _csv_response(rows: list[dict], filename: str, fieldnames: list[str]) -> StreamingResponse:
    """Serialize dictionaries as CSV for the format=csv option supported by all reports."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    if rows:
        writer.writerows(rows)
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/net-worth", response_model=NetWorthReport)
def report_net_worth(
    as_of_date: dt.date | None = Query(default=None),
    format: str = Query(default="json", pattern="^(json|csv)$"),
    db: Session = Depends(get_db, scope="function"),
):
    report = ReportService(db).net_worth(as_of_date=as_of_date)
    if format == "csv":
        return _csv_response(
            report.by_account,
            "net-worth.csv",
            ["account_id", "name", "balance"],
        )
    return report


@router.get("/net-worth/history", response_model=list[AccountsBalanceHistoryPoint])
def report_net_worth_history(db: Session = Depends(get_db, scope="function")):
    """Point-in-time net-worth history, including currently inactive accounts. Complements
    individual account history at /accounts/{id}/history.
    """
    return ReportService(db).accounts_balance_history()


@router.get("/income-statement", response_model=IncomeStatementReport)
def report_income_statement(
    date_from: dt.date | None = Query(default=None),
    date_to: dt.date | None = Query(default=None),
    format: str = Query(default="json", pattern="^(json|csv)$"),
    db: Session = Depends(get_db, scope="function"),
):
    report = ReportService(db).income_statement(date_from=date_from, date_to=date_to)
    if format == "csv":
        rows = [p.model_dump(mode="json") for p in report.periods]
        return _csv_response(rows, "income-statement.csv", list(IncomeStatementPeriod.model_fields))
    return report


@router.get("/spending-analysis", response_model=CategoryAnalysisReport)
def report_spending_analysis(
    date_from: dt.date | None = Query(default=None),
    date_to: dt.date | None = Query(default=None),
    format: str = Query(default="json", pattern="^(json|csv)$"),
    db: Session = Depends(get_db, scope="function"),
):
    report = ReportService(db).spending_analysis(date_from=date_from, date_to=date_to)
    if format == "csv":
        rows = [
            {
                "level": "top_level",
                **r.model_dump(mode="json"),
                "top_level_category_id": r.category_id,
            }
            for r in report.by_top_level_category
        ] + [{"level": "leaf", **r.model_dump(mode="json")} for r in report.by_category_detail]
        return _csv_response(
            rows,
            "spending-analysis.csv",
            ["level", *CategoryAnalysisDetailItem.model_fields],
        )
    return report


@router.get("/income-analysis", response_model=CategoryAnalysisReport)
def report_income_analysis(
    date_from: dt.date | None = Query(default=None),
    date_to: dt.date | None = Query(default=None),
    format: str = Query(default="json", pattern="^(json|csv)$"),
    db: Session = Depends(get_db, scope="function"),
):
    report = ReportService(db).income_analysis(date_from=date_from, date_to=date_to)
    if format == "csv":
        rows = [r.model_dump(mode="json") for r in report.by_category]
        return _csv_response(rows, "income-analysis.csv", list(CategoryAnalysisItem.model_fields))
    return report


@router.get("/transfer-analysis", response_model=CategoryAnalysisReport)
def report_transfer_analysis(
    date_from: dt.date | None = Query(default=None),
    date_to: dt.date | None = Query(default=None),
    format: str = Query(default="json", pattern="^(json|csv)$"),
    db: Session = Depends(get_db, scope="function"),
):
    report = ReportService(db).transfer_analysis(date_from=date_from, date_to=date_to)
    if format == "csv":
        rows = [r.model_dump(mode="json") for r in report.by_category]
        return _csv_response(
            rows,
            "transfer-analysis.csv",
            list(CategoryAnalysisItem.model_fields),
        )
    return report


@router.get("/securities-analysis", response_model=SecuritiesAnalysisReport)
def report_securities_analysis(
    format: str = Query(default="json", pattern="^(json|csv)$"),
    db: Session = Depends(get_db, scope="function"),
):
    """Analyze current open portfolio positions: allocation by type and rankings by value, gains,
    and losses.
    """
    report = ReportService(db).securities_analysis()
    if format == "csv":
        rows = [r.model_dump(mode="json") for r in report.positions]
        return _csv_response(
            rows,
            "securities-analysis.csv",
            list(SecurityPositionItem.model_fields),
        )
    return report


@router.get("/dividends-analysis", response_model=DividendsAnalysisReport)
def report_dividends_analysis(
    date_from: dt.date | None = Query(default=None),
    date_to: dt.date | None = Query(default=None),
    format: str = Query(default="json", pattern="^(json|csv)$"),
    db: Session = Depends(get_db, scope="function"),
):
    """Analyze coupons and dividends by year, seasonality, top-paying securities, and type."""
    report = ReportService(db).dividends_analysis(date_from=date_from, date_to=date_to)
    if format == "csv":
        rows = [r.model_dump(mode="json") for r in report.by_security]
        return _csv_response(
            rows,
            "dividends-analysis.csv",
            list(DividendBySecurity.model_fields),
        )
    return report


@router.get("/costs-analysis", response_model=CostsAnalysisReport)
def report_costs_analysis(
    date_from: dt.date | None = Query(default=None),
    date_to: dt.date | None = Query(default=None),
    format: str = Query(default="json", pattern="^(json|csv)$"),
    db: Session = Depends(get_db, scope="function"),
):
    """Analyze costs and taxes: gross realized results, grouped costs, and performance impact."""
    report = ReportService(db).costs_analysis(date_from=date_from, date_to=date_to)
    if format == "csv":
        rows = [
            {**i.model_dump(mode="json"), "group": g.group} for g in report.groups for i in g.items
        ]
        return _csv_response(
            rows,
            "costs-analysis.csv",
            [*CostItem.model_fields, "group"],
        )
    return report
