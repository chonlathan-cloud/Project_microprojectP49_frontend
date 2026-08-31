from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import JSONResponse

from app.auth import require_task_invoker
from app.processor import DeliveryState, process_export
from app.repository import ExportNotEligible, ExportRepositoryError, FirestoreExportRepository
from app.settings import get_settings

app = FastAPI(
    title="SPA 49 Accounting Worker",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
)


@lru_cache
def _repository() -> FirestoreExportRepository:
    return FirestoreExportRepository(get_settings())


async def get_repository() -> FirestoreExportRepository:
    return _repository()


@app.get("/health/live", tags=["health"])
async def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
async def ready() -> JSONResponse:
    settings = get_settings()
    errors = settings.runtime_readiness_errors()
    status_code = 200 if not errors else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if not errors else "not_ready",
            "dependencies": {"flowAccount": "ready" if not errors else "disabled"},
            "reasonCodes": list(errors),
        },
    )


@app.post("/internal/v1/tasks/accounting-exports/{export_id}")
async def deliver_accounting_export(
    export_id: str,
    _: Annotated[str, Depends(require_task_invoker)],
    repository: Annotated[FirestoreExportRepository, Depends(get_repository)],
) -> JSONResponse:
    try:
        outcome = await process_export(export_id, get_settings(), repository)
    except ExportNotEligible as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except ExportRepositoryError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error
    retryable = outcome.state is DeliveryState.RETRYABLE
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE if retryable else status.HTTP_200_OK,
        content={"exportId": export_id, "state": outcome.state},
    )


@app.post("/internal/v1/accounting-runs:nightly")
async def run_nightly_exports(
    _: Annotated[str, Depends(require_task_invoker)],
    repository: Annotated[FirestoreExportRepository, Depends(get_repository)],
) -> dict[str, object]:
    try:
        export_ids = await repository.due_export_ids()
    except ExportRepositoryError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error
    results: list[dict[str, str]] = []
    for export_id in export_ids:
        try:
            outcome = await process_export(export_id, get_settings(), repository)
            results.append({"exportId": export_id, "state": outcome.state})
        except ExportNotEligible:
            continue
        except ExportRepositoryError:
            results.append({"exportId": export_id, "state": "RETRYABLE"})
    return {"accepted": len(export_ids), "results": results}
