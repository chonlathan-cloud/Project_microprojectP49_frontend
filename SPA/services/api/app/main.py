from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.v1.public import router as public_router
from app.core.errors import DomainError

app = FastAPI(
    title="SPA 49 API",
    version="0.1.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
)
app.include_router(public_router)


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
    return {"status": "ready", "dependencies": {"catalogSeed": "ready"}}
