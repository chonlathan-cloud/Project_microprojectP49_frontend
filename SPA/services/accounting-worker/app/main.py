import asyncio
import json
import logging
from datetime import datetime, timedelta
from functools import lru_cache
from time import monotonic
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import JSONResponse

from app.auth import require_task_invoker
from app.client import (
    FlowAccountClient,
    FlowAccountConfigurationError,
    FlowAccountRetryableError,
)
from app.processor import DeliveryState, process_export
from app.repository import (
    ExportAlreadyFinal,
    ExportNotEligible,
    ExportRepositoryError,
    FirestoreExportRepository,
)
from app.settings import get_settings
from app.tasks import AccountingTaskEnqueuer

app = FastAPI(
    title="SPA 49 Accounting Worker",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
)
logger = logging.getLogger(__name__)

_provider_validation_lock = asyncio.Lock()
_provider_validation_expires_at = 0.0
_provider_validation_errors: tuple[str, ...] = ()


def _operational_log(event: str, **fields: object) -> None:
    logger.info(json.dumps({"event": event, **fields}, separators=(",", ":")))


@lru_cache
def _repository() -> FirestoreExportRepository:
    return FirestoreExportRepository(get_settings())


async def get_repository() -> FirestoreExportRepository:
    return _repository()


@lru_cache
def _task_enqueuer() -> AccountingTaskEnqueuer:
    return AccountingTaskEnqueuer(get_settings())


async def get_task_enqueuer() -> AccountingTaskEnqueuer:
    return _task_enqueuer()


@lru_cache
def _flowaccount_client() -> FlowAccountClient:
    return FlowAccountClient(get_settings())


async def _readiness_errors() -> tuple[str, ...]:
    global _provider_validation_errors, _provider_validation_expires_at
    settings = get_settings()
    errors = list(settings.runtime_readiness_errors())
    if errors:
        return tuple(errors)
    async with _provider_validation_lock:
        if monotonic() >= _provider_validation_expires_at:
            try:
                await _flowaccount_client().validate_configuration()
                _provider_validation_errors = ()
            except FlowAccountConfigurationError:
                _provider_validation_errors = ("FLOWACCOUNT_CONFIGURATION_MISMATCH",)
            except FlowAccountRetryableError:
                _provider_validation_errors = ("FLOWACCOUNT_DEPENDENCY_UNAVAILABLE",)
            _provider_validation_expires_at = monotonic() + 600
    return _provider_validation_errors


async def _require_ready() -> None:
    if await _readiness_errors():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Accounting integration is not ready",
        )


@app.get("/health/live", tags=["health"])
async def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
async def ready() -> JSONResponse:
    errors = await _readiness_errors()
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
    await _require_ready()
    try:
        outcome = await process_export(
            export_id,
            get_settings(),
            repository,
            client=_flowaccount_client(),
        )
    except ExportAlreadyFinal:
        return JSONResponse(status_code=status.HTTP_204_NO_CONTENT, content=None)
    except ExportNotEligible as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except ExportRepositoryError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error
    retryable = outcome.state is DeliveryState.RETRYABLE
    _operational_log(
        "accounting_export_delivery",
        exportId=export_id,
        result=outcome.state,
        safeErrorCode=outcome.safe_error_code,
        latencyMs=outcome.latency_ms,
    )
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE if retryable else status.HTTP_200_OK,
        content={"exportId": export_id, "state": outcome.state},
    )


@app.post("/internal/v1/tasks/accounting-runs/{run_id}")
async def orchestrate_accounting_run(
    run_id: str,
    _: Annotated[str, Depends(require_task_invoker)],
    repository: Annotated[FirestoreExportRepository, Depends(get_repository)],
    tasks: Annotated[AccountingTaskEnqueuer, Depends(get_task_enqueuer)],
) -> dict[str, object]:
    await _require_ready()
    try:
        await repository.start_enqueuing(run_id)
        scheduled = await repository.is_scheduled_run(run_id)
        export_ids = await repository.run_export_ids(run_id)
        newly_enqueued_count = 0
        for export_id in export_ids:
            try:
                generation = await repository.prepare_enqueue(export_id, run_id)
                await tasks.enqueue_export(export_id, generation)
                confirmed = await repository.confirm_enqueued(
                    export_id, run_id, generation
                )
                newly_enqueued_count += int(confirmed)
            except ExportNotEligible:
                continue
        if scheduled and len(export_ids) >= get_settings().nightly_batch_size:
            await repository.continue_enqueuing(
                run_id, selected_count=len(export_ids)
            )
            _operational_log(
                "accounting_run_continuation_requested",
                runId=run_id,
                selectedCount=len(export_ids),
                newlyEnqueuedCount=newly_enqueued_count,
            )
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Accounting run has more eligible backlog",
            )
        enqueued_count = await repository.finish_enqueuing(
            run_id,
            selected_count=len(export_ids),
            accumulate_selection=scheduled,
        )
    except ExportRepositoryError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error
    _operational_log(
        "accounting_run_enqueued",
        runId=run_id,
        selectedCount=len(export_ids),
        enqueuedCount=enqueued_count,
        newlyEnqueuedCount=newly_enqueued_count,
    )
    return {
        "runId": run_id,
        "selectedCount": len(export_ids),
        "enqueuedCount": enqueued_count,
        "newlyEnqueuedCount": newly_enqueued_count,
    }


@app.post("/internal/v1/accounting-runs:nightly", status_code=status.HTTP_202_ACCEPTED)
async def run_nightly_exports(
    principal: Annotated[str, Depends(require_task_invoker)],
    repository: Annotated[FirestoreExportRepository, Depends(get_repository)],
    tasks: Annotated[AccountingTaskEnqueuer, Depends(get_task_enqueuer)],
) -> dict[str, object]:
    await _require_ready()
    bangkok = ZoneInfo("Asia/Bangkok")
    local_now = datetime.now(bangkok)
    accounting_date = local_now.date() - timedelta(days=1)
    cutoff_at = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        run_id, created = await repository.create_nightly_run(
            accounting_date=accounting_date,
            cutoff_at=cutoff_at,
            requested_by=principal,
        )
        await tasks.enqueue_run(run_id)
    except ExportRepositoryError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error
    _operational_log(
        "accounting_nightly_requested",
        runId=run_id,
        accountingDate=accounting_date.isoformat(),
        created=created,
    )
    return {
        "runId": run_id,
        "created": created,
        "accountingDate": accounting_date.isoformat(),
        "cutoffAt": cutoff_at.isoformat(),
    }
