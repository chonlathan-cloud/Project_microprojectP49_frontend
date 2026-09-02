from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.application.cash_deposits import CashAllocationRequest, CashDepositService
from app.core.auth import require_admin_user
from app.core.errors import ValidationDomainError
from app.core.settings import get_settings
from app.core.types import AppRole
from app.domains.identity.models import AdminPrincipal
from app.infrastructure.cash_evidence import GcsCashEvidenceStore
from app.infrastructure.firestore_cash_deposits import FirestoreCashDepositRepository

router = APIRouter(prefix="/api/v1/admin", tags=["admin-cash-deposits"])
DepositId = Annotated[str, Path(pattern=r"^dep_[a-f0-9]{24}$")]
AttemptId = Annotated[str, Path(pattern=r"^cda_[a-f0-9]{24}$")]


def _camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.title() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True, extra="forbid")


class Allocation(ApiModel):
    payment_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    expected_version: int = Field(ge=1)


class CreateDepositRequest(ApiModel):
    branch_id: str = Field(min_length=1, max_length=128)
    allocations: list[Allocation] = Field(min_length=1, max_length=100)
    expected_total_satang: int = Field(gt=0)


class EvidenceAuthorizeRequest(ApiModel):
    content_type: str
    size_bytes: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")


class EvidenceConfirmRequest(ApiModel):
    generation: int = Field(gt=0)


class CreateAttemptRequest(ApiModel):
    expected_version: int = Field(ge=1)


class CancelRequest(ApiModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)


def _admin_principal(actor: dict[str, object]) -> AdminPrincipal:
    raw_branches = actor.get("branchIds")
    branch_ids = (
        tuple(str(branch_id) for branch_id in raw_branches if branch_id)
        if isinstance(raw_branches, list)
        else (get_settings().default_branch_id,)
    )
    return AdminPrincipal(
        uid=str(actor["uid"]),
        email=str(actor.get("email", "")),
        role=AppRole(str(actor["role"])),
        branch_ids=branch_ids,
    )


def _idempotency_key(value: Annotated[str, Header(alias="Idempotency-Key")]) -> str:
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise ValidationDomainError("Idempotency-Key must be a UUID v4") from error
    if parsed.version != 4:
        raise ValidationDomainError("Idempotency-Key must be a UUID v4")
    return str(parsed)


@lru_cache
def _cash_deposit_service() -> CashDepositService:
    settings = get_settings()
    return CashDepositService(
        FirestoreCashDepositRepository(settings),
        GcsCashEvidenceStore(settings),
        settings,
    )


async def get_cash_deposit_service() -> CashDepositService:
    return _cash_deposit_service()


@router.get("/cash-payments/unsettled")
async def list_unsettled_cash(
    response: Response,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    service: Annotated[CashDepositService, Depends(get_cash_deposit_service)],
    branch_id: Annotated[str, Query(alias="branchId")] = "branch_001",
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store, private"
    return {"items": await service.list_unsettled(_admin_principal(actor), branch_id)}


@router.post("/cash-deposits", status_code=status.HTTP_201_CREATED)
async def create_cash_deposit(
    request: CreateDepositRequest,
    response: Response,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    idempotency_key: Annotated[str, Depends(_idempotency_key)],
    service: Annotated[CashDepositService, Depends(get_cash_deposit_service)],
) -> dict:
    result = await service.create(
        principal=_admin_principal(actor),
        branch_id=request.branch_id,
        allocations=tuple(
            CashAllocationRequest(item.payment_id, item.expected_version)
            for item in request.allocations
        ),
        expected_total_satang=request.expected_total_satang,
        idempotency_key=idempotency_key,
    )
    response.headers["Cache-Control"] = "no-store, private"
    return result


@router.get("/cash-deposits/{deposit_id}")
async def get_cash_deposit(
    deposit_id: DepositId,
    response: Response,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    service: Annotated[CashDepositService, Depends(get_cash_deposit_service)],
) -> dict:
    response.headers["Cache-Control"] = "no-store, private"
    return await service.get(deposit_id, _admin_principal(actor))


@router.post("/cash-deposits/{deposit_id}/evidence-upload:authorize")
async def authorize_evidence_upload(
    deposit_id: DepositId,
    request: EvidenceAuthorizeRequest,
    response: Response,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    service: Annotated[CashDepositService, Depends(get_cash_deposit_service)],
) -> dict[str, object]:
    result = await service.authorize_evidence(
        deposit_id=deposit_id,
        principal=_admin_principal(actor),
        content_type=request.content_type,
        size_bytes=request.size_bytes,
        sha256_hex=request.sha256,
    )
    response.headers["Cache-Control"] = "no-store, private"
    return {
        "evidenceId": result.evidence_id,
        "uploadUrl": result.upload_url,
        "objectName": result.object_name,
        "expiresAt": result.expires_at,
    }


@router.post("/cash-deposits/{deposit_id}/evidence:confirm")
async def confirm_evidence(
    deposit_id: DepositId,
    request: EvidenceConfirmRequest,
    response: Response,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    service: Annotated[CashDepositService, Depends(get_cash_deposit_service)],
) -> dict:
    response.headers["Cache-Control"] = "no-store, private"
    return await service.confirm_evidence(
        deposit_id=deposit_id, principal=_admin_principal(actor), generation=request.generation
    )


@router.post("/cash-deposits/{deposit_id}/evidence-read:authorize")
async def authorize_evidence_read(
    deposit_id: DepositId,
    response: Response,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    service: Annotated[CashDepositService, Depends(get_cash_deposit_service)],
) -> dict[str, object]:
    url, expires_at = await service.authorize_evidence_read(deposit_id, _admin_principal(actor))
    response.headers["Cache-Control"] = "no-store, private"
    return {"readUrl": url, "expiresAt": expires_at}


@router.post("/cash-deposits/{deposit_id}/attempts", status_code=status.HTTP_201_CREATED)
async def create_deposit_attempt(
    deposit_id: DepositId,
    request: CreateAttemptRequest,
    response: Response,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    idempotency_key: Annotated[str, Depends(_idempotency_key)],
    service: Annotated[CashDepositService, Depends(get_cash_deposit_service)],
) -> dict:
    response.headers["Cache-Control"] = "no-store, private"
    return await service.create_attempt(
        deposit_id=deposit_id,
        principal=_admin_principal(actor),
        expected_version=request.expected_version,
        idempotency_key=idempotency_key,
    )


@router.post("/cash-deposit-attempts/{attempt_id}:reconcile")
async def reconcile_deposit_attempt(
    attempt_id: AttemptId,
    response: Response,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    service: Annotated[CashDepositService, Depends(get_cash_deposit_service)],
) -> dict:
    response.headers["Cache-Control"] = "no-store, private"
    return await service.reconcile(attempt_id, _admin_principal(actor))


@router.post("/cash-deposits/{deposit_id}:cancel")
async def cancel_cash_deposit(
    deposit_id: DepositId,
    request: CancelRequest,
    response: Response,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    service: Annotated[CashDepositService, Depends(get_cash_deposit_service)],
) -> dict:
    response.headers["Cache-Control"] = "no-store, private"
    return await service.cancel(
        deposit_id=deposit_id,
        principal=_admin_principal(actor),
        expected_version=request.expected_version,
        reason=request.reason,
    )
