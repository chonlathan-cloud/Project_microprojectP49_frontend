from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, status
from google.cloud import firestore
from pydantic import BaseModel, ConfigDict, Field

from app.domains.campaigns.service import claim_campaign, get_public_campaign
from app.infrastructure.firestore import get_firestore_client
from app.integrations.line_identity import verify_line_id_token

router = APIRouter(prefix="/api/v1/public/campaigns", tags=["campaigns"])


def _camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.title() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True)


class CampaignClaimRequest(ApiModel):
    full_name: str = Field(min_length=2, max_length=160)
    phone: str = Field(min_length=7, max_length=30)
    birth_day: int = Field(ge=1, le=31)
    birth_month: int = Field(ge=1, le=12)
    birth_year: int = Field(ge=1900, le=2100)
    gender: Literal["FEMALE", "MALE", "NON_BINARY", "PREFER_NOT_TO_SAY"] | None = None
    privacy_acknowledged: bool
    birthday_marketing_consent: bool = False
    line_friendship_confirmed: bool = False
    line_id_token: str = Field(min_length=20, max_length=4096)


@router.get("/{campaign_code}")
async def get_campaign(
    campaign_code: str,
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> dict[str, object]:
    return get_public_campaign(client, campaign_code)


@router.post("/{campaign_code}/claims", status_code=status.HTTP_201_CREATED)
async def create_campaign_claim(
    campaign_code: str,
    request: CampaignClaimRequest,
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
    idempotency_key: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    identity = verify_line_id_token(request.line_id_token)
    return claim_campaign(
        client,
        campaign_code=campaign_code,
        full_name=request.full_name,
        phone=request.phone,
        birth_day=request.birth_day,
        birth_month=request.birth_month,
        birth_year=request.birth_year,
        gender=request.gender,
        privacy_acknowledged=request.privacy_acknowledged,
        birthday_marketing_consent=request.birthday_marketing_consent,
        line_friendship_confirmed=request.line_friendship_confirmed,
        idempotency_key=idempotency_key,
        line_identity=identity,
    )
