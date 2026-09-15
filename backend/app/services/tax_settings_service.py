"""Service: TaxSettingsService."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.tax_settings import TaxSetting
from app.repositories.tax_settings_repo import TaxSettingRepository
from app.utils.errors import NotFoundError, ValidationErrorPFIM
from app.utils.numeric_limits import normalize_numeric_8_4

DEFAULT_RATES = {
    "capital_gains_tax_rate": Decimal("26.00"),
    "dividend_withholding_it": Decimal("26.00"),
    "dividend_withholding_us": Decimal("15.00"),
    "stamp_duty_rate": Decimal("0.20"),
}
_MIN_RATE = Decimal("0")
_MAX_RATE = Decimal("100")


class TaxSettingsService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = TaxSettingRepository(db)

    def list_settings(self) -> list[TaxSetting]:
        return self.repo.list()

    def get_rate(self, key: str) -> Decimal:
        """Read a tax rate, falling back to its built-in default when absent from the database,
        such as in unseeded in-memory tests.
        """
        setting = self.repo.get(key)
        if setting is not None:
            return self._normalize_rate(key, Decimal(setting.value))
        if key in DEFAULT_RATES:
            return self._normalize_rate(key, DEFAULT_RATES[key])
        raise NotFoundError(f"Tax rate '{key}' not found", detail={"key": key})

    def update_setting(self, key: str, value: Decimal) -> TaxSetting:
        return self.repo.upsert(key, self._normalize_rate(key, value))

    @staticmethod
    def _normalize_rate(key: str, value: Decimal) -> Decimal:
        """Normalize a tax percentage and limit it to the valid range. Service-level validation
        also covers internal callers and historical database values.
        """
        try:
            normalized = normalize_numeric_8_4(value, label=f"Tax rate '{key}'")
        except ValueError as exc:
            raise ValidationErrorPFIM(
                str(exc),
                detail={"field": "value", "key": key, "value": str(value)},
            ) from exc
        if not _MIN_RATE <= normalized <= _MAX_RATE:
            raise ValidationErrorPFIM(
                f"Tax rate '{key}' must be between 0 and 100",
                detail={
                    "field": "value",
                    "key": key,
                    "value": str(normalized),
                    "minimum": str(_MIN_RATE),
                    "maximum": str(_MAX_RATE),
                },
            )
        return normalized
