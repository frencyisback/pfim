"""Bootstrap the capability token used by HTTP mutations."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from app.config import settings
from app.security import CAPABILITY_HEADER, capability_authority, validate_request_origin

router = APIRouter(prefix="/security", tags=["security"])


class CapabilityResponse(BaseModel):
    token: str
    header_name: str


@router.get("/capability", response_model=CapabilityResponse)
def issue_capability(request: Request, response: Response) -> CapabilityResponse:
    """Return the volatile token only to an allowed local HTTP context."""

    validate_request_origin(request, settings.mutation_origins_list)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return CapabilityResponse(
        token=capability_authority.issue(),
        header_name=CAPABILITY_HEADER,
    )
