"""Bounded reading and consistent decoding of uploaded CSV files."""

from __future__ import annotations

from fastapi import UploadFile

from app.config import settings
from app.utils.errors import PayloadTooLargeError, ValidationErrorPFIM

READ_CHUNK_SIZE = 64 * 1024


async def read_csv_upload(file: UploadFile, *, max_bytes: int | None = None) -> str:
    """Read a CSV without exceeding the configured byte limit. Check incoming chunks rather than
    trusting optional content-length or calling unbounded read(). Support UTF-8 with BOM.
    """

    limit = settings.csv_upload_max_bytes if max_bytes is None else max_bytes
    if limit <= 0:
        raise RuntimeError("csv_upload_max_bytes must be greater than zero")

    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = await file.read(READ_CHUNK_SIZE)
        if not chunk:
            break
        size += len(chunk)
        if size > limit:
            raise PayloadTooLargeError(
                "The CSV file exceeds the maximum allowed size",
                detail={"max_bytes": limit, "received_bytes_at_least": size},
            )
        chunks.append(chunk)

    try:
        return b"".join(chunks).decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationErrorPFIM(
            "The CSV file is not encoded in UTF-8",
            detail={"encoding": "utf-8", "byte_offset": exc.start},
        ) from exc
