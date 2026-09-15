"""HTTP safeguards for the local application. CORS protects response reads but cannot prevent
hostile pages from sending simple POSTs. Mutations therefore require a process-local secret
obtained by a GET that passes Host and Origin checks. The in-memory token changes whenever the
backend restarts.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterable

from fastapi import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.utils.errors import PFIMError

CAPABILITY_HEADER = "X-PFIM-Capability"
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class OriginForbiddenError(PFIMError):
    status_code = 403
    error_code = "ORIGIN_FORBIDDEN"


class CapabilityAuthority:
    """Issue and verify the current process capability token."""

    def __init__(self) -> None:
        # 256 random bits; never written to disk or logs.
        self._token = secrets.token_urlsafe(32)

    def issue(self) -> str:
        return self._token

    def verify(self, candidate: str | None) -> bool:
        return candidate is not None and secrets.compare_digest(candidate, self._token)


capability_authority = CapabilityAuthority()


def _normalise_origins(origins: Iterable[str]) -> frozenset[str]:
    return frozenset(origin.rstrip("/") for origin in origins if origin)


def validate_request_origin(request: Request, allowed_origins: Iterable[str]) -> None:
    """Reject disallowed Origins while allowing non-browser clients. A missing Origin is not
    authentication: mutations still require a capability token. The bootstrap GET also uses
    this check to prevent cross-origin JavaScript from reading the secret.
    """

    origin = request.headers.get("origin")
    if origin is not None and origin.rstrip("/") not in _normalise_origins(allowed_origins):
        raise OriginForbiddenError(
            "Unauthorized HTTP Origin",
            detail={"origin": origin},
        )


class MutationSecurityMiddleware:
    """Block mutations without a valid Origin and capability token."""

    def __init__(self, app: ASGIApp, allowed_origins: Iterable[str]) -> None:
        self.app = app
        self.allowed_origins = _normalise_origins(allowed_origins)

    @staticmethod
    async def _deny(
        scope: Scope,
        receive: Receive,
        send: Send,
        error_code: str,
        message: str,
    ) -> None:
        response = JSONResponse(
            status_code=403,
            content={"error_code": error_code, "message": message, "detail": {}},
            headers={"Cache-Control": "no-store"},
        )
        await response(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method", "").upper() not in _UNSAFE_METHODS:
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        origin = request.headers.get("origin")
        if origin is not None and origin.rstrip("/") not in self.allowed_origins:
            await self._deny(
                scope,
                receive,
                send,
                "ORIGIN_FORBIDDEN",
                "Unauthorized HTTP Origin",
            )
            return

        provided = request.headers.get(CAPABILITY_HEADER)
        if provided is None:
            await self._deny(
                scope,
                receive,
                send,
                "CAPABILITY_REQUIRED",
                f"Header {CAPABILITY_HEADER} is required for this operation",
            )
            return
        if not capability_authority.verify(provided):
            await self._deny(
                scope,
                receive,
                send,
                "CAPABILITY_INVALID",
                "Invalid capability token",
            )
            return

        await self.app(scope, receive, send)
