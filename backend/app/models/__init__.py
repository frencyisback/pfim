"""Centralized imports of all ORM models. Alembic autogeneration and Base.metadata need these
imports to discover every table. Add each new model here.
"""

from app.models.account import Account
from app.models.category import Category
from app.models.csv_import_profile import CsvImportProfile
from app.models.forecast_scenario import ForecastScenario
from app.models.fx_rate import FxRate
from app.models.income_event import IncomeEvent
from app.models.portfolio_cost import PortfolioCost
from app.models.price import Price
from app.models.security import Security
from app.models.tax_event import TaxEvent
from app.models.tax_settings import TaxSetting
from app.models.trade import Trade
from app.models.trade_cost import TradeCost
from app.models.transaction import Transaction

__all__ = [
    "Account",
    "Category",
    "CsvImportProfile",
    "ForecastScenario",
    "FxRate",
    "IncomeEvent",
    "PortfolioCost",
    "Price",
    "Security",
    "TaxEvent",
    "TaxSetting",
    "Trade",
    "TradeCost",
    "Transaction",
]
