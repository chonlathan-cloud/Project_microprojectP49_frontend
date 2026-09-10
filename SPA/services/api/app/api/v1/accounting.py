from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.auth import require_admin_user
from app.core.errors import DependencyUnavailable, PermissionDenied, ValidationDomainError
from app.core.settings import get_settings
from app.core.types import PaymentSource
from app.infrastructure.accounting_tasks import (
    AccountingTaskEnqueuer,
    AccountingTaskUnavailable,
)
from app.infrastructure.firestore import get_firestore_client
from app.infrastructure.firestore_accounting import FirestoreAccountingRepository

router = APIRouter(prefix="/api/v1/admin", tags=["admin-accounting"])

ExportStatusFilter = Literal[
    "READY",
    "ENQUEUE_PENDING",
    "ENQUEUED",
    "PROCESSING",
    "RETRYABLE",
    "RECONCILE_REQUIRED",
    "REVIEW_REQUIRED",
    "SYNCED",
]
PaymentSourceFilter = Literal["BEAM", "CASH", "BANK_TRANSFER"]
CashSettlementFilter = Literal[
    "NOT_APPLICABLE", "UNSETTLED", "DEPOSIT_PENDING", "SETTLED", "REVIEW"
]


def _camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.title() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_camel,
        populate_by_name=True,
        extra="forbid",
    )


class AccountingRunFilter(ApiModel):
    branch_id: str = "branch_001"


class CreateAccountingRunRequest(ApiModel):
    export_ids: list[str] | None = Field(default=None, min_length=1, max_length=100)
    filter: AccountingRunFilter | None = None

    @model_validator(mode="after")
    def exactly_one_scope(self) -> "CreateAccountingRunRequest":
        if (self.export_ids is None) == (self.filter is None):
            raise ValueError("Provide exportIds or filter, but not both")
        return self


class RecordHistoricalPaymentRequest(ApiModel):
    payment_source: Literal["CASH", "BANK_TRANSFER"]
    paid_at: datetime
    expected_version: int = Field(ge=1)
    confirmed: bool

    @model_validator(mode="after")
    def validate_paid_at(self) -> "RecordHistoricalPaymentRequest":
        if self.paid_at.tzinfo is None or self.paid_at.utcoffset() is None:
            raise ValueError("Historical paid time must include a timezone offset")
        return self


@lru_cache
def _tasks() -> AccountingTaskEnqueuer:
    return AccountingTaskEnqueuer(get_settings())


def get_task_enqueuer() -> AccountingTaskEnqueuer:
    return _tasks()


def get_accounting_repository(
    client: Annotated[object, Depends(get_firestore_client)],
) -> FirestoreAccountingRepository:
    return FirestoreAccountingRepository(get_settings(), client)


def _branch_ids(actor: dict[str, object]) -> tuple[str, ...]:
    raw = actor.get("branchIds")
    if isinstance(raw, list):
        values = tuple(str(value) for value in raw if value)
        if values:
            return values
    return (get_settings().default_branch_id,)


def _require_sync_permission(actor: dict[str, object]) -> None:
    if actor.get("role") != "ADMIN":
        raise PermissionDenied("ADMIN role is required for accounting sync")


def _idempotency_key(
    value: Annotated[str, Header(alias="Idempotency-Key")],
) -> str:
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise ValidationDomainError("Idempotency-Key must be a UUID v4") from error
    if parsed.version != 4:
        raise ValidationDomainError("Idempotency-Key must be a UUID v4")
    return str(parsed)


def _enqueue_run(tasks: AccountingTaskEnqueuer, run_id: str) -> None:
    try:
        tasks.enqueue_run(run_id)
    except AccountingTaskUnavailable as error:
        raise DependencyUnavailable("Accounting worker queue is unavailable") from error


@router.get("/payments")
def list_accounting_payments(
    response: Response,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    repository: Annotated[
        FirestoreAccountingRepository, Depends(get_accounting_repository)
    ],
    branch_id: Annotated[str, Query(alias="branchId")] = "branch_001",
    date_from: Annotated[date | None, Query(alias="dateFrom")] = None,
    date_to: Annotated[date | None, Query(alias="dateTo")] = None,
    export_status: Annotated[ExportStatusFilter | None, Query(alias="exportStatus")] = None,
    payment_source: Annotated[PaymentSourceFilter | None, Query(alias="paymentSource")] = None,
    cash_settlement_status: Annotated[
        CashSettlementFilter | None, Query(alias="cashSettlementStatus")
    ] = None,
    requires_attention: Annotated[bool, Query(alias="requiresAttention")] = False,
    search: Annotated[str, Query(max_length=100)] = "",
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 25,
    page_token: Annotated[
        str | None, Query(alias="pageToken", max_length=2048)
    ] = None,
) -> dict[str, object]:
    if branch_id not in _branch_ids(actor):
        raise ValidationDomainError("Branch is outside the Admin scope")
    start = date_from or datetime.now(ZoneInfo("Asia/Bangkok")).date()
    end_inclusive = date_to or start
    if end_inclusive < start or (end_inclusive - start).days > 366:
        raise ValidationDomainError("Accounting date range is invalid")
    result = repository.list_payments(
        branch_id=branch_id,
        date_from=start,
        date_to=end_inclusive + timedelta(days=1),
        export_status=export_status,
        payment_source=payment_source,
        cash_settlement_status=cash_settlement_status,
        requires_attention=requires_attention,
        search=search,
        page_size=page_size,
        page_token=page_token,
    )
    response.headers["Cache-Control"] = "no-store, private"
    result["permissions"] = {
        "read": True,
        "sync": actor.get("role") == "ADMIN",
        "cashDeposit": actor.get("role") == "ADMIN"
        and not get_settings().cash_deposit_readiness_errors(),
    }
    return result


@router.get("/payments/{payment_id}")
def accounting_payment_detail(
    payment_id: str,
    response: Response,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    repository: Annotated[
        FirestoreAccountingRepository, Depends(get_accounting_repository)
    ],
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store, private"
    return repository.detail(payment_id, branch_ids=_branch_ids(actor))


@router.get("/historical-accounting-candidates")
def list_historical_accounting_candidates(
    response: Response,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    repository: Annotated[
        FirestoreAccountingRepository, Depends(get_accounting_repository)
    ],
    branch_id: Annotated[str, Query(alias="branchId")] = "branch_001",
) -> dict[str, object]:
    _require_sync_permission(actor)
    if branch_id not in _branch_ids(actor):
        raise ValidationDomainError("Branch is outside the Admin scope")
    response.headers["Cache-Control"] = "no-store, private"
    return repository.list_pending_historical(branch_id=branch_id)


@router.post("/historical-accounting-candidates/{booking_id}:record")
def record_historical_accounting_payment(
    booking_id: str,
    request: RecordHistoricalPaymentRequest,
    response: Response,
    idempotency_key: Annotated[str, Depends(_idempotency_key)],
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    repository: Annotated[
        FirestoreAccountingRepository, Depends(get_accounting_repository)
    ],
) -> dict[str, object]:
    _require_sync_permission(actor)
    if not request.confirmed:
        raise ValidationDomainError("Historical payment confirmation is required")
    result = repository.record_historical_payment(
        booking_public_id=booking_id,
        branch_ids=_branch_ids(actor),
        actor_uid=str(actor["uid"]),
        payment_source=PaymentSource(request.payment_source),
        paid_at=request.paid_at,
        expected_version=request.expected_version,
        idempotency_key=idempotency_key,
    )
    response.headers["Cache-Control"] = "no-store, private"
    return result


@router.post(
    "/accounting-sync-runs",
    status_code=status.HTTP_202_ACCEPTED,
)
def create_accounting_sync_run(
    request: CreateAccountingRunRequest,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    idempotency_key: Annotated[str, Depends(_idempotency_key)],
    repository: Annotated[
        FirestoreAccountingRepository, Depends(get_accounting_repository)
    ],
    tasks: Annotated[AccountingTaskEnqueuer, Depends(get_task_enqueuer)],
) -> dict[str, object]:
    _require_sync_permission(actor)
    branch_ids = _branch_ids(actor)
    if request.export_ids is not None:
        export_ids = tuple(dict.fromkeys(request.export_ids))
    else:
        assert request.filter is not None
        if request.filter.branch_id not in branch_ids:
            raise ValidationDomainError("Branch is outside the Admin scope")
        export_ids = repository.eligible_export_ids(
            branch_ids=(request.filter.branch_id,), operation="SYNC"
        )
    run_id, created = repository.create_run(
        actor_uid=str(actor["uid"]),
        branch_ids=branch_ids,
        export_ids=export_ids,
        operation="SYNC",
        idempotency_key=idempotency_key,
    )
    _enqueue_run(tasks, run_id)
    return {"runId": run_id, "created": created, "status": "PENDING"}


def _create_export_action_run(
    *,
    export_id: str,
    operation: Literal["SYNC", "RETRY", "RECONCILE"],
    actor: dict[str, object],
    idempotency_key: str,
    repository: FirestoreAccountingRepository,
    tasks: AccountingTaskEnqueuer,
) -> dict[str, object]:
    _require_sync_permission(actor)
    run_id, created = repository.create_run(
        actor_uid=str(actor["uid"]),
        branch_ids=_branch_ids(actor),
        export_ids=(export_id,),
        operation=operation,
        idempotency_key=idempotency_key,
    )
    _enqueue_run(tasks, run_id)
    return {"runId": run_id, "created": created, "status": "PENDING"}


@router.post(
    "/accounting-exports/{export_id}:retry",
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_accounting_export(
    export_id: str,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    idempotency_key: Annotated[str, Depends(_idempotency_key)],
    repository: Annotated[
        FirestoreAccountingRepository, Depends(get_accounting_repository)
    ],
    tasks: Annotated[AccountingTaskEnqueuer, Depends(get_task_enqueuer)],
) -> dict[str, object]:
    return _create_export_action_run(
        export_id=export_id,
        operation="RETRY",
        actor=actor,
        idempotency_key=idempotency_key,
        repository=repository,
        tasks=tasks,
    )


@router.post(
    "/accounting-exports/{export_id}:reconcile",
    status_code=status.HTTP_202_ACCEPTED,
)
def reconcile_accounting_export(
    export_id: str,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    idempotency_key: Annotated[str, Depends(_idempotency_key)],
    repository: Annotated[
        FirestoreAccountingRepository, Depends(get_accounting_repository)
    ],
    tasks: Annotated[AccountingTaskEnqueuer, Depends(get_task_enqueuer)],
) -> dict[str, object]:
    return _create_export_action_run(
        export_id=export_id,
        operation="RECONCILE",
        actor=actor,
        idempotency_key=idempotency_key,
        repository=repository,
        tasks=tasks,
    )


@router.get("/accounting-sync-runs/{run_id}")
def get_accounting_sync_run(
    run_id: str,
    response: Response,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    repository: Annotated[
        FirestoreAccountingRepository, Depends(get_accounting_repository)
    ],
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store, private"
    return repository.get_run(run_id, branch_ids=_branch_ids(actor))
