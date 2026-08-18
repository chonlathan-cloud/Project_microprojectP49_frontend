from app.core.types import PricingMode
from app.domains.catalog.seed import load_catalog_manifest


def test_catalog_has_approved_inventory() -> None:
    manifest = load_catalog_manifest()
    variants = [variant for service in manifest.services for variant in service.variants]
    assert len(manifest.services) == 11
    assert len(variants) == 17


def test_catalog_has_bilingual_customer_descriptions() -> None:
    manifest = load_catalog_manifest()
    assert all(service.description_th.strip() for service in manifest.services)
    assert all(service.description_en.strip() for service in manifest.services)


def test_catalog_preserves_known_lamenatt_source_spelling() -> None:
    manifest = load_catalog_manifest()
    service = next(item for item in manifest.services if item.id == "lamenatt-oil")
    assert service.name_en == "Lamenatt Oil Massage"


def test_couple_package_seed_is_charge_once() -> None:
    manifest = load_catalog_manifest()
    variant = next(
        variant
        for service in manifest.services
        for variant in service.variants
        if variant.id == "couple-relaxation-90"
    )
    assert variant.price_satang == 119000
    assert variant.pricing_mode is PricingMode.PER_BOOKING
    assert variant.required_pax == 2
