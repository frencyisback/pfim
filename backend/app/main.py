"""FastAPI entry point for PFIM Backend."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import settings
from app.database import engine
from app.maintenance import (
    MaintenanceGateMiddleware,
    backend_instance_lock,
)
from app.routers import (
    accounts,
    backup,
    categories,
    csv_import_profiles,
    forecasts,
    fx_rates,
    income_events,
    performance,
    portfolio,
    portfolio_costs,
    prices,
    reports,
    securities,
    security,
    tax_events,
    tax_settings,
    trades,
    transactions,
)
from app.schema_guard import code_alembic_heads, ensure_database_schema_current
from app.security import CAPABILITY_HEADER, MutationSecurityMiddleware
from app.services.restore_service import recover_pending_restore, restore_runtime_status
from app.utils.errors import PFIMError


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Check the schema before accepting requests. This read-only guard leaves migrations to an
    explicit administrative operation with the backend stopped and the target verified.
    """

    if engine.url.get_backend_name() != "sqlite" or engine.url.database in {
        None,
        "",
        ":memory:",
    }:
        ensure_database_schema_current(engine)
        yield
        return

    db_path = Path(str(engine.url.database)).resolve()
    heads = code_alembic_heads()
    if len(heads) != 1:
        raise RuntimeError("PFIM restore requires a single Alembic head")
    expected_revision = settings.expected_alembic_revision.strip() or heads[0]
    instance = backend_instance_lock(db_path.parent)
    with instance.hold(timeout=0):
        recover_pending_restore(
            db_path=db_path,
            engine=engine,
            expected_revision=expected_revision,
            lock_timeout=float(settings.restore_quiesce_timeout_seconds),
        )
        ensure_database_schema_current(engine)
        try:
            yield
        finally:
            engine.dispose()


app = FastAPI(
    title=settings.app_name,
    description="Personal Finance & Investment Manager - Local API",
    # Keep aligned with the latest CHANGELOG.md entry: this version is shown in /docs, where
    # API callers can read it.
    #
    version="0.22.0",
    lifespan=lifespan,
)

app.add_middleware(
    MutationSecurityMiddleware,
    allowed_origins=settings.mutation_origins_list,
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts_list)
app.add_middleware(
    MaintenanceGateMiddleware,
    control_paths={"/api/v1/health", "/api/v1/backup/status"},
)
# The last middleware added is outermost. Authorized origins must be able to read early
# security and maintenance rejections, otherwise browsers hide CAPABILITY_INVALID and
# prevent token renewal after a restart. Preflight requests invoke no handlers or writes.
#
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", CAPABILITY_HEADER],
)


@app.exception_handler(PFIMError)
def pfim_error_handler(request: Request, exc: PFIMError) -> JSONResponse:
    """Convert every PFIMError into the standard error response schema."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error_code": exc.error_code,
            "message": exc.message,
            "detail": exc.detail,
        },
    )


def _describe_validation_error(error: dict) -> str:
    """Format a Pydantic validation error as one readable line. Use the final loc component as
    the field name and omit the body/query/path prefix.
    """
    field = ".".join(str(part) for part in error.get("loc", ())[1:]) or "request"
    return f"{field}: {error.get('msg', "invalid value")}"


@app.exception_handler(RequestValidationError)
def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Convert validation failures into the standard application error schema. Expose the message
    field the frontend reads, including missing fields and invalid ranges, instead of
    FastAPI's default detail-only response.
    """
    errors = exc.errors()
    return JSONResponse(
        status_code=422,
        content={
            "error_code": "VALIDATION_ERROR",
            "message": "; ".join(_describe_validation_error(e) for e in errors)
            or "Invalid request data",
            "detail": {"fields": [_describe_validation_error(e) for e in errors]},
        },
    )


app.include_router(transactions.router, prefix=settings.api_v1_prefix)
app.include_router(accounts.router, prefix=settings.api_v1_prefix)
app.include_router(categories.router, prefix=settings.api_v1_prefix)
app.include_router(csv_import_profiles.router, prefix=settings.api_v1_prefix)
app.include_router(securities.router, prefix=settings.api_v1_prefix)
app.include_router(trades.router, prefix=settings.api_v1_prefix)
app.include_router(prices.router, prefix=settings.api_v1_prefix)
app.include_router(fx_rates.router, prefix=settings.api_v1_prefix)
app.include_router(income_events.router, prefix=settings.api_v1_prefix)
app.include_router(portfolio.router, prefix=settings.api_v1_prefix)
app.include_router(portfolio_costs.router, prefix=settings.api_v1_prefix)
app.include_router(tax_events.router, prefix=settings.api_v1_prefix)
app.include_router(tax_settings.router, prefix=settings.api_v1_prefix)
app.include_router(performance.router, prefix=settings.api_v1_prefix)
app.include_router(reports.router, prefix=settings.api_v1_prefix)
app.include_router(forecasts.router, prefix=settings.api_v1_prefix)
app.include_router(backup.router, prefix=settings.api_v1_prefix)
app.include_router(security.router, prefix=settings.api_v1_prefix)


@app.get("/api/v1/health", tags=["health"])
def health_check() -> dict:
    """Health check confirming that the server is running."""
    runtime = (
        restore_runtime_status(Path(str(engine.url.database)).resolve().parent)
        if engine.url.get_backend_name() == "sqlite"
        and engine.url.database not in {None, "", ":memory:"}
        else {
            "maintenance_mode": False,
            "restore_state": "idle",
            "active_restore_id": None,
        }
    )
    return {
        "status": "maintenance" if runtime["maintenance_mode"] else "ok",
        "app": settings.app_name,
        "env": settings.app_env,
        "restore_state": runtime["restore_state"],
        "active_restore_id": runtime["active_restore_id"],
    }


def _pfim_openapi() -> dict:
    """Expose the capability header required for mutations in Swagger."""

    if app.openapi_schema is not None:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=(
            f"{app.description}\n\n"
            "Mutating operations require a temporary capability token. "
            "Obtain it with `GET /api/v1/security/capability`, then use "
            "**Authorize** and paste it into the PFIMCapability field."
        ),
        routes=app.routes,
    )
    components = schema.setdefault("components", {})
    security_schemes = components.setdefault("securitySchemes", {})
    security_schemes["PFIMCapability"] = {
        "type": "apiKey",
        "in": "header",
        "name": CAPABILITY_HEADER,
        "description": "Temporary token obtained from GET /api/v1/security/capability",
    }
    for path_item in schema.get("paths", {}).values():
        for method in ("post", "put", "patch", "delete"):
            operation = path_item.get(method)
            if operation is not None:
                operation["security"] = [{"PFIMCapability": []}]
    app.openapi_schema = schema
    return schema


app.openapi = _pfim_openapi
