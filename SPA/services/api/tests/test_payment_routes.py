from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.api.v1 import payments as payment_routes
from app.application.payments import (
    CustomerPaymentResult,
    PaymentAttemptResult,
    PaymentOptions,
    PaymentStatusResult,
)
from app.core.auth import require_admin_user
from app.core.types import BeamPaymentMethod, PaymentSource, PaymentStatus
from app.main import app


class Payments:
    async def options(self, booking_id, principal, device_type=None):
        assert booking_id == "BK-001"
        assert principal.user_id == "U-trusted"
        return PaymentOptions(
            booking_id="BK-001",
            payment_id="pay_001",
            status=PaymentStatus.DUE,
            source=None,
            service_amount_satang=35_000,
            currency="THB",
            eligible=True,
            reason=None,
            tip_presets_satang=(0, 2_000, 5_000, 10_000),
            custom_tip_max_satang=50_000,
            enabled_methods=(
                BeamPaymentMethod.KPLUS,
                BeamPaymentMethod.SCB_EASY,
                BeamPaymentMethod.KRUNGSRI_APP,
                BeamPaymentMethod.BANGKOK_BANK_APP,
                BeamPaymentMethod.QR_PROMPT_PAY,
            ),
            version=1,
        )

    async def admin_options(self, booking_id, principal):
        result = await self.options(booking_id, type("Principal", (), {"user_id": "U-trusted"})())
        return result

    async def create_attempt(self, **kwargs):
        assert kwargs["tip_amount_satang"] == 2_000
        return PaymentAttemptResult(
            attempt_id="pat_001",
            payment_id="pay_001",
            status="ACTIVE",
            payment_method=BeamPaymentMethod.KPLUS,
            action_required="REDIRECT",
            expires_at=datetime(2026, 8, 31, 8, 0, tzinfo=UTC),
            status_token="opaque-status-token",
            redirect_url="https://checkout.beamcheckout.com/test",
        )

    async def resolve_status(self, token):
        assert token == "opaque-status-token-which-is-long-enough"
        return PaymentStatusResult(
            payment_id="pay_001",
            booking_id="BK-001",
            status=PaymentStatus.PAID,
            source=PaymentSource.BEAM,
            service_amount_satang=35_000,
            tip_amount_satang=2_000,
            gross_amount_satang=37_000,
            paid_at=datetime(2026, 8, 31, 7, 50, tzinfo=UTC),
        )

    async def resolve_customer_attempt(self, attempt_id, principal):
        assert attempt_id == "pat_001"
        assert principal.user_id == "U-trusted"
        assert principal.channel_id == "line-channel"
        return CustomerPaymentResult(
            payment_id="pay_001",
            booking_id="BK-001",
            status=PaymentStatus.PAID,
            source=PaymentSource.BEAM,
            service_amount_satang=35_000,
            tip_amount_satang=2_000,
            gross_amount_satang=37_000,
            paid_at=datetime(2026, 8, 31, 7, 50, tzinfo=UTC),
            attempt_id="pat_001",
            payment_method=BeamPaymentMethod.KPLUS,
        )

    async def record_cash(self, **kwargs):
        assert kwargs["principal"].role == "ADMIN"
        return PaymentStatusResult(
            payment_id="pay_001",
            booking_id="BK-001",
            status=PaymentStatus.PAID,
            source=PaymentSource.CASH,
            service_amount_satang=35_000,
            tip_amount_satang=0,
            gross_amount_satang=35_000,
            paid_at=datetime(2026, 8, 31, 7, 50, tzinfo=UTC),
        )


def test_customer_payment_routes_use_line_identity_and_no_store(monkeypatch) -> None:
    previous_overrides = app.dependency_overrides.copy()
    monkeypatch.setattr(
        payment_routes,
        "verify_line_id_token",
        lambda token: {"sub": "U-trusted", "aud": "line-channel"},
    )
    app.dependency_overrides[payment_routes.get_payment_service] = lambda: Payments()
    client = TestClient(app)
    try:
        options = client.post(
            "/api/v1/public/bookings/BK-001/payment-options",
            json={"lineIdToken": "line-token", "deviceType": "IOS"},
        )
        assert options.status_code == 200
        assert options.headers["cache-control"] == "no-store, private"
        assert options.json()["tipPresetsSatang"] == [0, 2_000, 5_000, 10_000]
        assert options.json()["methods"] == [
            "KPLUS",
            "SCB_EASY",
            "KRUNGSRI_APP",
            "BANGKOK_BANK_APP",
            "QR_PROMPT_PAY",
        ]

        attempt = client.post(
            "/api/v1/public/bookings/BK-001/payment-attempts",
            headers={"Idempotency-Key": "2d4e72d3-4ab8-4f99-a09a-c81fa1caa49c"},
            json={
                "lineIdToken": "line-token",
                "tipAmountSatang": 2_000,
                "paymentMethod": "KPLUS",
                "deviceType": "IOS",
            },
        )
        assert attempt.status_code == 201
        assert attempt.json()["actionRequired"] == "REDIRECT"
        assert attempt.json()["paymentMethod"] == "KPLUS"

        resolved = client.post(
            "/api/v1/public/payment-status:resolve",
            json={"statusToken": "opaque-status-token-which-is-long-enough"},
        )
        assert resolved.status_code == 200
        assert resolved.json()["status"] == "PAID"

        customer_result = client.post(
            "/api/v1/public/payment-attempts/pat_001:resolve",
            json={"lineIdToken": "line-token"},
        )
        assert customer_result.status_code == 200
        assert customer_result.headers["cache-control"] == "no-store, private"
        assert customer_result.json()["attemptId"] == "pat_001"
        assert customer_result.json()["paymentMethod"] == "KPLUS"
        assert customer_result.json()["status"] == "PAID"
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)


def test_cash_receipt_requires_admin_confirmation() -> None:
    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[payment_routes.get_payment_service] = lambda: Payments()
    app.dependency_overrides[require_admin_user] = lambda: {
        "uid": "admin-uid",
        "email": "admin@example.com",
        "role": "ADMIN",
        "branchIds": ["branch_001"],
    }
    client = TestClient(app)
    headers = {"Idempotency-Key": "2d4e72d3-4ab8-4f99-a09a-c81fa1caa49c"}
    try:
        options = client.post(
            "/api/v1/admin/bookings/BK-001/payment-options",
        )
        assert options.status_code == 200
        assert options.json()["version"] == 1

        denied = client.post(
            "/api/v1/admin/bookings/BK-001/payments:record-cash",
            headers=headers,
            json={"tipAmountSatang": 0, "expectedVersion": 1, "confirmed": False},
        )
        assert denied.status_code == 422

        recorded = client.post(
            "/api/v1/admin/bookings/BK-001/payments:record-cash",
            headers=headers,
            json={"tipAmountSatang": 0, "expectedVersion": 1, "confirmed": True},
        )
        assert recorded.status_code == 200
        assert recorded.json()["source"] == "CASH"
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)
