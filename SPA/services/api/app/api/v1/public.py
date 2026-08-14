from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from app.domains.catalog.seed import load_catalog_manifest

router = APIRouter(prefix="/api/v1/public", tags=["public"])


def _to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.title() for part in rest)


class ParticipantAvailabilityRequest(BaseModel):
    model_config = ConfigDict(alias_generator=lambda value: _to_camel(value), populate_by_name=True)
    service_variant_id: str


class AvailabilityRequest(BaseModel):
    model_config = ConfigDict(alias_generator=lambda value: _to_camel(value), populate_by_name=True)
    branch_id: str
    date_from: str
    date_to: str
    participants: list[ParticipantAvailabilityRequest] = Field(min_length=1, max_length=2)

@router.get("/branch")
async def get_branch() -> dict[str, object]:
    return {
        "branchId": "branch_001",
        "name": "SPA 49",
        "timezone": "Asia/Bangkok",
        "currency": "THB",
        "bookingWindow": {"minDays": 1, "maxDays": 30},
        "resourceConfigurationReady": False,
    }


@router.get("/services")
async def get_services() -> dict[str, object]:
    manifest = load_catalog_manifest()
    return {
        "catalogVersion": manifest.catalog_version,
        "items": [
            {
                "id": service.id,
                "category": service.category,
                "nameTh": service.name_th,
                "nameEn": service.name_en,
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


@router.post("/availability/search")
async def search_availability(request: AvailabilityRequest) -> dict[str, object]:
    """Return no slots until approved resource compatibility/capacity is configured."""
    return {
        "branchId": request.branch_id,
        "timezone": "Asia/Bangkok",
        "generatedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "slots": [],
        "configurationState": "RESOURCE_CONFIGURATION_REQUIRED",
    }
