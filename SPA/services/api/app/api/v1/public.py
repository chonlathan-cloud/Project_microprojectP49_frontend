from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from google.cloud import firestore
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.errors import DependencyUnavailable, NotFoundDomainError, ValidationDomainError
from app.core.settings import get_settings
from app.domains.bookings.plan import build_booking_plan
from app.domains.bookings.service import _variant
from app.domains.capacity.availability import (
    availability_response,
    search_capacity_slots,
)
from app.domains.catalog.seed import load_catalog_manifest
from app.infrastructure.firestore import get_firestore_client
from app.infrastructure.storage import get_service_assets_bucket

router = APIRouter(prefix="/api/v1/public", tags=["public"])


def _to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.title() for part in rest)


class ParticipantServiceAvailabilityRequest(BaseModel):
    model_config = ConfigDict(alias_generator=_to_camel, populate_by_name=True)
    service_variant_id: str = Field(min_length=1, max_length=160)


class ParticipantAvailabilityRequest(BaseModel):
    model_config = ConfigDict(alias_generator=_to_camel, populate_by_name=True)
    service_variant_id: str | None = Field(default=None, min_length=1, max_length=160)
    services: list[ParticipantServiceAvailabilityRequest] = Field(
        default_factory=list, max_length=3
    )

    @model_validator(mode="after")
    def validate_service_contract(self) -> ParticipantAvailabilityRequest:
        if bool(self.service_variant_id) == bool(self.services):
            raise ValueError("Provide either serviceVariantId or services")
        return self


class AvailabilityRequest(BaseModel):
    model_config = ConfigDict(alias_generator=_to_camel, populate_by_name=True)
    branch_id: str
    date_from: str
    date_to: str
    participants: list[ParticipantAvailabilityRequest] = Field(min_length=1, max_length=2)


@router.get("/branch")
async def get_branch(
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> dict[str, object]:
    snapshot = client.collection("branches").document("branch_001").get()
    data = snapshot.to_dict() if snapshot.exists else {}
    return {
        "branchId": "branch_001",
        "name": data.get("name", "SPA49"),
        "phone": data.get("phone", "0643654949"),
        "address": data.get(
            "address", "53/72 ถนนเฉลิมพระเกียรติ ร.9 แขวงหนองบอน เขตประเวศ กรุงเทพมหานคร 10250"
        ),
        "mapUrl": data.get("mapUrl"),
        "timezone": "Asia/Bangkok",
        "currency": "THB",
        "operatingHours": data.get(
            "operatingHours",
            {str(index): {"open": "10:00", "close": "22:00"} for index in range(7)},
        ),
        "bookingWindow": data.get("bookingWindow", {"minDays": 1, "maxDays": 30}),
        "resourceConfigurationReady": int(
            data.get("activeCapacityUnits", data.get("capacityUnits", 0))
        )
        > 0,
        "priceIncludesVat": True,
    }


@router.get("/services")
async def get_services(
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> dict[str, object]:
    manifest = load_catalog_manifest()
    seed_by_id = {service.id: service for service in manifest.services}
    try:
        snapshots = client.collection("services").where("active", "==", True).stream()
        items = []
        for snapshot in snapshots:
            service = snapshot.to_dict() or {}
            service_id = str(service.get("serviceId", snapshot.id))
            seed = seed_by_id.get(service_id)
            image = service.get("image") if isinstance(service.get("image"), dict) else {}
            items.append(
                {
                    "id": service_id,
                    "category": service.get("category"),
                    "nameTh": service.get("nameTh"),
                    "nameEn": service.get("nameEn"),
                    "descriptionTh": service.get("descriptionTh")
                    or (seed.description_th if seed else ""),
                    "descriptionEn": service.get("descriptionEn")
                    or (seed.description_en if seed else ""),
                    "active": True,
                    "displayOrder": int(service.get("displayOrder", 0)),
                    "imageVersion": image.get("version"),
                    "variants": [
                        {
                            "id": variant.get("variantId"),
                            "durationMinutes": variant.get("durationMinutes"),
                            "priceSatang": variant.get("priceSatang"),
                            "pricingMode": variant.get("pricingMode"),
                            "requiredPax": variant.get("requiredPax"),
                        }
                        for variant in service.get("variants", [])
                        if variant.get("active", True)
                    ],
                }
            )
        if items:
            items.sort(key=lambda item: int(item["displayOrder"]))
            return {"catalogVersion": "firestore", "items": items}
    except Exception:
        pass
    return {
        "catalogVersion": manifest.catalog_version,
        "items": [
            {
                "id": service.id,
                "category": service.category,
                "nameTh": service.name_th,
                "nameEn": service.name_en,
                "descriptionTh": service.description_th,
                "descriptionEn": service.description_en,
                "active": service.active,
                "displayOrder": service.display_order,
                "imageVersion": None,
                "variants": [
                    {
                        "id": variant.id,
                        "durationMinutes": variant.duration_minutes,
                        "priceSatang": variant.price_satang,
                        "pricingMode": variant.pricing_mode,
                        "requiredPax": variant.required_pax,
                    }
                    for variant in service.variants
                    if variant.active
                ],
            }
            for service in manifest.services
            if service.active
        ],
    }


@router.get("/services/{service_id}/image")
async def get_service_image(
    service_id: str,
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
    v: str | None = None,
) -> Response:
    snapshot = client.collection("services").document(service_id).get()
    data = snapshot.to_dict() or {} if snapshot.exists else {}
    image = data.get("image") if isinstance(data.get("image"), dict) else {}
    object_path = str(image.get("objectPath", ""))
    if not object_path:
        raise NotFoundDomainError("Service image not found")
    if v and v != image.get("version"):
        raise NotFoundDomainError("Service image version not found")
    try:
        content = get_service_assets_bucket().blob(object_path).download_as_bytes()
    except Exception as error:
        raise DependencyUnavailable("Service image is temporarily unavailable") from error
    return Response(
        content=content,
        media_type="image/webp",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.post("/availability/search")
async def search_availability(
    request: AvailabilityRequest,
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> dict[str, object]:
    try:
        plan = build_booking_plan(
            [participant.model_dump(by_alias=True) for participant in request.participants],
            lambda variant_id: _variant(client, variant_id),
            max_services_per_participant=get_settings().max_services_per_participant,
        )
    except ValidationDomainError:
        return availability_response(request.branch_id, [], "INVALID_PARTICIPANT_CONFIGURATION")
    return search_capacity_slots(
        client,
        branch_id=request.branch_id,
        date_from=request.date_from,
        date_to=request.date_to,
        participant_duration_minutes=list(plan.participant_duration_minutes),
        mode="PUBLIC",
    )
