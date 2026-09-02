from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.accounting import router as accounting_router
from app.api.v1.analytics import router as analytics_router
from app.api.v1.bookings import router as bookings_router
from app.api.v1.campaign_admin import router as campaign_admin_router
from app.api.v1.campaigns import router as campaigns_router
from app.api.v1.cash_deposits import router as cash_deposit_router
from app.api.v1.operations import router as operations_router
from app.api.v1.payments import admin_router as payment_admin_router
from app.api.v1.payments import public_router as payment_public_router
from app.api.v1.payments import webhook_router as payment_webhook_router
from app.api.v1.public import router as public_router
from app.api.v1.webhooks import router as webhooks_router
from app.core.errors import DomainError
from app.core.settings import get_settings
from app.infrastructure.firestore import check_firestore_connection

settings = get_settings()

app = FastAPI(
    title="SPA 49 API",
    version="0.1.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
)
app.include_router(public_router)
app.include_router(bookings_router)
app.include_router(campaigns_router)
app.include_router(campaign_admin_router)
app.include_router(operations_router)
app.include_router(webhooks_router)
app.include_router(payment_public_router)
app.include_router(payment_admin_router)
app.include_router(payment_webhook_router)
app.include_router(accounting_router)
app.include_router(analytics_router)
app.include_router(cash_deposit_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Idempotency-Key"],
)


@app.exception_handler(DomainError)
async def handle_domain_error(request: Request, error: DomainError) -> JSONResponse:
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    return JSONResponse(
        status_code=error.status_code,
        media_type="application/problem+json",
        content={
            "type": f"https://spa49.invalid/errors/{error.code.lower().replace('_', '-')}",
            "title": error.detail,
            "status": error.status_code,
            "code": error.code,
            "requestId": request_id,
            "detail": error.detail,
            "fieldErrors": [],
        },
    )


@app.get("/health/live", tags=["health"])
async def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
async def ready() -> dict[str, object]:
    firestore_ready, firestore_error = check_firestore_connection()
    dependencies: dict[str, object] = {
        "catalogSeed": "ready",
        "beamPaymentConfiguration": (
            "ready" if not settings.beam_readiness_errors() else "not_ready"
        ),
        "accountingConfiguration": (
            "ready" if not settings.accounting_readiness_errors() else "not_ready"
        ),
        "cashDepositConfiguration": (
            "disabled"
            if not settings.cash_deposit_enabled
            else "ready"
            if not settings.cash_deposit_readiness_errors()
            else "not_ready"
        ),
        "firestore": {
            "status": "ready" if firestore_ready else "unavailable",
            "database": settings.firestore_database,
        },
    }
    if firestore_error:
        dependencies["firestore"] = {
            "status": "unavailable",
            "database": settings.firestore_database,
            "error": firestore_error,
        }
    reason_codes = [
        *settings.beam_readiness_errors(),
        *settings.accounting_readiness_errors(),
        *(settings.cash_deposit_readiness_errors() if settings.cash_deposit_enabled else ()),
    ]
    return {
        "status": "ready" if firestore_ready and not reason_codes else "degraded",
        "dependencies": dependencies,
        "reasonCodes": reason_codes,
    }
