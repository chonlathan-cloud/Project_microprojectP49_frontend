from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Response
from google.cloud import firestore
from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import DependencyUnavailable, NotFoundDomainError
from app.domains.bookings.service import _bucket_id, _variant
from app.domains.capacity.buckets import required_bucket_starts
from app.domains.catalog.seed import load_catalog_manifest
from app.infrastructure.firestore import get_firestore_client
from app.infrastructure.storage import get_service_assets_bucket

router = APIRouter(prefix="/api/v1/public", tags=["public"])
TZ = ZoneInfo("Asia/Bangkok")


def _to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.title() for part in rest)


class ParticipantAvailabilityRequest(BaseModel):
    model_config = ConfigDict(alias_generator=_to_camel, populate_by_name=True)
    service_variant_id: str


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
    branch_snapshot = client.collection("branches").document(request.branch_id).get()
    if not branch_snapshot.exists:
        return _availability_response(request.branch_id, [], "RESOURCE_CONFIGURATION_REQUIRED")
    branch = branch_snapshot.to_dict() or {}
    capacity = int(branch.get("activeCapacityUnits", branch.get("capacityUnits", 0)))
    if capacity <= 0:
        return _availability_response(request.branch_id, [], "RESOURCE_CONFIGURATION_REQUIRED")

    variants = [
        _variant(client, participant.service_variant_id)[1] for participant in request.participants
    ]
    if any(item.required_pax == 2 for item in variants) and (
        len(variants) != 2 or len({item.id for item in variants}) != 1
    ):
        return _availability_response(request.branch_id, [], "INVALID_PARTICIPANT_CONFIGURATION")
    duration = max(item.duration_minutes for item in variants)
    units = len(variants)
    try:
        day_from, day_to = (
            date.fromisoformat(request.date_from),
            date.fromisoformat(request.date_to),
        )
    except ValueError:
        return _availability_response(request.branch_id, [], "INVALID_DATE_RANGE")
    if day_to < day_from or (day_to - day_from).days > 31:
        return _availability_response(request.branch_id, [], "INVALID_DATE_RANGE")

    slots: list[dict[str, object]] = []
    day = day_from
    while day <= day_to:
        closure = list(
            client.collection("special_closures")
            .where("branchId", "==", request.branch_id)
            .where("localDate", "==", day.isoformat())
            .limit(1)
            .stream()
        )
        if not closure:
            hours = (branch.get("operatingHours") or {}).get(
                str(day.weekday()), {"open": "10:00", "close": "22:00"}
            )
            open_time = time.fromisoformat(hours.get("open", "10:00"))
            close_time = time.fromisoformat(hours.get("close", "22:00"))
            cursor = datetime.combine(day, open_time, TZ)
            closing = datetime.combine(day, close_time, TZ)
            while cursor + timedelta(minutes=duration) <= closing:
                min_days = int((branch.get("bookingWindow") or {}).get("minDays", 1))
                if cursor <= datetime.now(TZ) + timedelta(days=min_days):
                    cursor += timedelta(minutes=15)
                    continue
                bucket_starts = required_bucket_starts(
                    cursor, duration, int(branch.get("bufferMinutes", 0))
                )
                bucket_snapshots = [
                    client.collection("capacity_buckets")
                    .document(_bucket_id(request.branch_id, item))
                    .get()
                    for item in bucket_starts
                ]
                available = min(
                    capacity - int((snapshot.to_dict() or {}).get("usedUnits", 0))
                    if snapshot.exists
                    else capacity
                    for snapshot in bucket_snapshots
                )
                if available >= units:
                    slots.append(
                        {
                            "localDate": day.isoformat(),
                            "localStartTime": cursor.strftime("%H:%M"),
                            "availableUnits": available,
                        }
                    )
                cursor += timedelta(minutes=15)
        day += timedelta(days=1)
    return _availability_response(
        request.branch_id, slots, "READY" if slots else "CAPACITY_UNAVAILABLE"
    )


def _availability_response(
    branch_id: str, slots: list[dict[str, object]], state: str
) -> dict[str, object]:
    return {
        "branchId": branch_id,
        "timezone": "Asia/Bangkok",
        "generatedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "slots": slots,
        "configurationState": state,
    }
