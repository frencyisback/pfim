"""Application exceptions and error responses. Every application error returns error_code,
message, and a detail object.
"""

from __future__ import annotations

from typing import Any


class PFIMError(Exception):
    """Base application exception."""

    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"

    def __init__(self, message: str, detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


class ValidationErrorPFIM(PFIMError):
    """HTTP 400: invalid input, such as a negative amount where prohibited."""

    status_code = 400
    error_code = "VALIDATION_ERROR"


class NotFoundError(PFIMError):
    """HTTP 404: resource not found."""

    status_code = 404
    error_code = "NOT_FOUND"


class ConflictError(PFIMError):
    """HTTP 409: logical conflict, such as selling more than the held quantity."""

    status_code = 409
    error_code = "CONFLICT"


class PayloadTooLargeError(PFIMError):
    """HTTP 413: payload exceeds a declared application limit."""

    status_code = 413
    error_code = "PAYLOAD_TOO_LARGE"


class DatabaseBusyError(PFIMError):
    """HTTP 503: another SQLite writer temporarily holds the database. Callers may retry the
    whole operation; the backend never automatically repeats non-idempotent mutations because
    a lost response could otherwise cause duplicate writes.
    """

    status_code = 503
    error_code = "DATABASE_BUSY"


class DatabaseLockedError(PFIMError):
    """HTTP 503: internal SQLite conflict requiring diagnosis rather than blind retries."""

    status_code = 503
    error_code = "DATABASE_LOCKED"
