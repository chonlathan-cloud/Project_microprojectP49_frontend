from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from google.cloud import firestore
from pydantic import BaseModel, ConfigDict, Field

from app.core.auth import require_admin_user
from app.domains.campaigns.admin_service import (
    actor_branch_ids,
    export_campaign_customers_csv,
    list_campaign_customers,
    list_campaigns,
    permissions_for,
    reveal_customer_pii,
    search_coupon,
    transition_campaign,
    transition_coupon,
    update_campaign,
)
from app.infrastructure.firestore import get_firestore_client

router = APIRouter(prefix="/api/v1/admin", tags=["campaign-admin"])


def _camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.title() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True)


class CampaignUpdate(ApiModel):
    expected_version: int = Field(ge=1)
    name_th: str | None = Field(default=None, min_length=2, max_length=160)
    name_en: str | None = Field(default=None, min_length=2, max_length=160)
    description_th: str | None = Field(default=None, max_length=1000)
    description_en: str | None = Field(default=None, max_length=1000)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    coupon_expires_at: datetime | None = None
    amount_satang: int | None = Field(default=None, gt=0)


class CampaignTransition(ApiModel):
    target_status: Literal["ACTIVE", "PAUSED", "ENDED"]
    expected_version: int = Field(ge=1)
    command_id: str = Field(min_length=8, max_length=128)


class PiiAccess(ApiModel):
    branch_id: str = Field(min_length=2, max_length=100)
    reason: str = Field(min_length=5, max_length=300)


class CrmExport(ApiModel):
    branch_id: str = Field(min_length=2, max_length=100)
    campaign_code: str | None = Field(default=None, max_length=100)


class CouponAction(ApiModel):
    branch_id: str = Field(min_length=2, max_length=100)
    expected_version: int = Field(ge=1)
    command_id: str = Field(min_length=8, max_length=128)
    reason: str | None = Field(default=None, max_length=300)


@router.get("/me")
async def get_admin_context(
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
) -> dict[str, object]:
    return {
        "role": actor.get("role"),
        "roleLabel": "OWNER / MANAGER" if actor.get("role") == "ADMIN" else "RECEPTIONIST",
        "branchIds": actor_branch_ids(actor),
        "permissions": permissions_for(actor),
    }


@router.get("/campaigns")
async def get_campaigns(
    branch_id: Annotated[str, Query(alias="branchId")],
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> dict[str, object]:
    return {"items": list_campaigns(client, actor, branch_id)}


@router.patch("/campaigns/{campaign_code}")
async def patch_campaign(
    campaign_code: str,
    request: CampaignUpdate,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> dict[str, object]:
    values = request.model_dump(by_alias=True, exclude={"expected_version"}, exclude_unset=True)
    return update_campaign(client, actor, campaign_code, values, request.expected_version)


@router.post("/campaigns/{campaign_code}:transition")
async def post_campaign_transition(
    campaign_code: str,
    request: CampaignTransition,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> dict[str, object]:
    return transition_campaign(
        client,
        actor,
        campaign_code,
        request.target_status,
        request.expected_version,
        request.command_id,
    )


@router.get("/campaign-customers")
async def get_campaign_customers(
    branch_id: Annotated[str, Query(alias="branchId")],
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
    campaign_code: Annotated[str | None, Query(alias="campaignCode")] = None,
    marketing_status: Annotated[
        Literal["GRANTED", "DENIED"] | None, Query(alias="marketingStatus")
    ] = None,
    query: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> dict[str, object]:
    return {
        "items": list_campaign_customers(
            client, actor, branch_id, campaign_code, marketing_status, query, limit
        )
    }


@router.post("/campaign-customers/{customer_id}/pii-access")
async def post_pii_access(
    customer_id: str,
    request: PiiAccess,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> dict[str, object]:
    return reveal_customer_pii(client, actor, customer_id, request.branch_id, request.reason)


@router.post("/campaign-customers:export")
async def post_crm_export(
    request: CrmExport,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> Response:
    content = export_campaign_customers_csv(client, actor, request.branch_id, request.campaign_code)
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="spa49-campaign-customers.csv"'},
    )


@router.get("/coupons:search")
async def get_coupon_by_code(
    code: str,
    branch_id: Annotated[str, Query(alias="branchId")],
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> dict[str, object]:
    return search_coupon(client, actor, branch_id, code)


@router.post("/coupons/{coupon_id}:redeem")
async def post_coupon_redeem(
    coupon_id: str,
    request: CouponAction,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> dict[str, object]:
    return transition_coupon(
        client,
        actor,
        coupon_id,
        "REDEEMED",
        request.branch_id,
        request.expected_version,
        request.command_id,
    )


@router.post("/coupons/{coupon_id}:void")
async def post_coupon_void(
    coupon_id: str,
    request: CouponAction,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> dict[str, object]:
    return transition_coupon(
        client,
        actor,
        coupon_id,
        "VOID",
        request.branch_id,
        request.expected_version,
        request.command_id,
        request.reason,
    )
