import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.types import PricingMode


def _to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.title() for part in rest)


class ResourceRequirementSeed(BaseModel):
    model_config = ConfigDict(alias_generator=lambda value: _to_camel(value), populate_by_name=True)

    resource_type: str
    units: int = Field(gt=0)
    compatible_resource_ids: list[str] = Field(default_factory=list)
    compatible_tags: list[str] = Field(default_factory=list)


class VariantSeed(BaseModel):
    model_config = ConfigDict(alias_generator=lambda value: _to_camel(value), populate_by_name=True)

    id: str
    duration_minutes: int = Field(gt=0)
    price_satang: int = Field(ge=0)
    pricing_mode: PricingMode
    required_pax: int = Field(ge=1, le=2)
    active: bool
    resource_requirements: list[ResourceRequirementSeed]

    @model_validator(mode="after")
    def validate_pricing_mode(self) -> "VariantSeed":
        if self.pricing_mode is PricingMode.PER_PARTICIPANT and self.required_pax != 1:
            raise ValueError("PER_PARTICIPANT variants require one participant")
        # Business Logic 7.1 explicitly approves the 20-minute Hot Compress even though
        # TDD 11 otherwise requires customer durations to align to 15-minute buckets.
        if self.duration_minutes % 15 and self.id != "hot-compress-neck-shoulder-back-20":
            raise ValueError("Customer-bookable duration must align to 15-minute buckets")
        return self


class ServiceSeed(BaseModel):
    model_config = ConfigDict(alias_generator=lambda value: _to_camel(value), populate_by_name=True)

    id: str
    category: str
    name_th: str
    name_en: str
    display_order: int
    active: bool
    variants: list[VariantSeed]


class CatalogManifest(BaseModel):
    model_config = ConfigDict(alias_generator=lambda value: _to_camel(value), populate_by_name=True)

    catalog_version: str
    source: str
    branch_id: str
    services: list[ServiceSeed]

    @model_validator(mode="after")
    def validate_inventory(self) -> "CatalogManifest":
        variant_ids = [variant.id for service in self.services for variant in service.variants]
        if len(self.services) != 11 or len(variant_ids) != 17:
            raise ValueError("Phase 1 seed must contain exactly 11 services and 17 variants")
        if len(variant_ids) != len(set(variant_ids)):
            raise ValueError("Variant IDs must be unique")
        return self


@lru_cache(maxsize=1)
def load_catalog_manifest() -> CatalogManifest:
    path = Path(__file__).resolve().parents[5] / "infra" / "seed" / "service-catalog.v1.json"
    return CatalogManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))
