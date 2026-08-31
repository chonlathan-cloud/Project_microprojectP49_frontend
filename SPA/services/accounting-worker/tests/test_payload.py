from datetime import date

import pytest
from pydantic import SecretStr, ValidationError

from app.contracts import ExportProjection, ServiceLineSnapshot
from app.payload import build_cash_invoice_payload, satang_to_baht
from app.settings import Settings


def settings() -> Settings:
    return Settings(
        sync_enabled=True,
        sandbox_contract_proven=True,
        api_base_url="https://sandbox.flowaccount.invalid/v1",
        client_id=SecretStr("test-client"),
        client_secret=SecretStr("test-secret"),
        contact_id="contact-test-001",
        other_channel_id="other-test-001",
        project_id="project-test-001",
    )


def export(**overrides: object) -> ExportProjection:
    values: dict[str, object] = {
        "export_id": "fa_export_001",
        "payment_id": "pay_001",
        "booking_public_id": "BK-20260831-001",
        "accounting_date": date(2026, 8, 31),
        "external_reference": "SPA-PAY-pay_001",
        "external_document_id": "SPAPAY-ABCDEF",
        "payment_source": "BEAM",
        "currency": "THB",
        "service_amount_satang": 35_000,
        "tip_amount_satang": 0,
        "gross_amount_satang": 35_000,
        "service_lines": (
            ServiceLineSnapshot(
                sku="FOOT-60",
                name="นวดเท้า 60 นาที",
                quantity=1,
                unit_amount_satang=35_000,
            ),
        ),
    }
    values.update(overrides)
    return ExportProjection.model_validate(values)


def test_satang_conversion_never_uses_binary_float() -> None:
    assert satang_to_baht(35_000) == "350.00"
    assert satang_to_baht(1) == "0.01"


def test_beam_payload_uses_other_channel_and_vat_inclusive() -> None:
    payload = build_cash_invoice_payload(export(), settings())
    assert payload["isVatInclusive"] is True
    assert payload["payment"] == {
        "paymentMethod": 13,
        "paymentDate": "2026-08-31",
        "amount": "350.00",
        "otherChannelId": "other-test-001",
    }
    assert payload["items"][0]["unitPrice"] == "350.00"


def test_tip_is_a_separate_traceable_line() -> None:
    projection = export(tip_amount_satang=5_000, gross_amount_satang=40_000)
    payload = build_cash_invoice_payload(projection, settings())
    assert len(payload["items"]) == 2
    assert payload["items"][1]["productCode"] == "SPA-TIP"
    assert payload["items"][1]["unitPrice"] == "50.00"
    assert payload["internalNotes"] == "Tip for BK-20260831-001"


def test_cash_payload_has_no_beam_channel() -> None:
    payload = build_cash_invoice_payload(export(payment_source="CASH"), settings())
    assert payload["payment"]["paymentMethod"] == 1
    assert "otherChannelId" not in payload["payment"]


def test_mismatched_service_or_gross_total_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Gross amount"):
        export(gross_amount_satang=35_001)
    with pytest.raises(ValidationError, match="Service lines"):
        export(service_amount_satang=34_999, gross_amount_satang=34_999)


def test_sync_is_fail_closed_without_bootstrap_proof() -> None:
    disabled = Settings()
    assert not disabled.ready_for_sync
    with pytest.raises(ValueError, match="not ready"):
        build_cash_invoice_payload(export(), disabled)


def test_test_environment_cannot_target_production_api() -> None:
    unsafe = settings().model_copy(update={"api_base_url": "https://openapi.flowaccount.com/v1"})
    assert unsafe.readiness_errors() == ("TEST_USES_PRODUCTION_URL",)


def test_production_environment_only_allows_official_api() -> None:
    unsafe = settings().model_copy(
        update={"environment": "prod", "api_base_url": "https://example.invalid/v1"}
    )
    assert unsafe.readiness_errors() == ("PRODUCTION_API_BASE_URL_INVALID",)
