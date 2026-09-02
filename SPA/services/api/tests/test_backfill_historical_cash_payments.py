from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.core.types import CashSettlementStatus, PaymentSource, PaymentStatus
from scripts.backfill_historical_cash_payments import (
    FIXTURE_KIND,
    PaymentEvidence,
    SourceDocument,
    build_plan,
    load_evidence,
    parse_args,
    plan_digest,
)


def booking(document_id: str = "booking-1", **overrides: object) -> SourceDocument:
    data = {
        "publicBookingId": "BK-20260820-001",
        "branchId": "branch_001",
        "status": "RECORDED",
        "adminEntryMode": "HISTORICAL_RECORD",
        "historicalFinancialRecord": True,
        "financiallyExcluded": False,
        "paymentStatus": "UNAVAILABLE",
        "subtotalAmountSatang": 30_000,
        "discountAmountSatang": 0,
        "estimatedAmountSatang": 30_000,
        "tipAmountSatang": 5_000,
        "grossAmountSatang": 35_000,
    }
    data.update(overrides)
    return SourceDocument(document_id, data)


def line(document_id: str = "line-1", **overrides: object) -> SourceDocument:
    data = {
        "bookingDocId": "booking-1",
        "financiallyExcluded": False,
        "quantity": 1,
        "lineTotalSatang": 30_000,
        "serviceSnapshot": {
            "serviceId": "traditional-thai",
            "variantId": "traditional-thai-60",
            "nameTh": "นวดแผนไทย 60 นาที",
        },
    }
    data.update(overrides)
    return SourceDocument(document_id, data)


def evidence() -> tuple[PaymentEvidence, ...]:
    return (
        PaymentEvidence(
            "BK-20260820-001",
            datetime.fromisoformat("2026-08-20T14:00:00+07:00"),
        ),
    )


def test_plan_creates_authoritative_cash_payment_and_ready_export() -> None:
    plan = build_plan(
        [booking()],
        [line()],
        evidence(),
        environment="prod",
        authorized_by="admin-001",
        authorization_reference="finance-approval-001",
    )

    assert plan.database == "spa-db"
    assert plan.write_count == 5
    assert plan.gross_amount_satang == 35_000
    record = plan.records[0]
    assert record.payment.status is PaymentStatus.PAID
    assert record.payment.source is PaymentSource.CASH
    assert record.payment.cash_received_by == "admin-001"
    assert record.payment.cash_settlement_status is CashSettlementStatus.REVIEW
    assert record.export.status == "READY"
    assert record.export.accounting_date == date(2026, 8, 20)
    assert record.export.gross_amount_satang == 35_000


def test_plan_derives_missing_legacy_gross_snapshot() -> None:
    plan = build_plan(
        [booking(grossAmountSatang=None)],
        [line()],
        evidence(),
        environment="prod",
        authorized_by="admin-001",
        authorization_reference="finance-approval-001",
    )

    assert plan.records[0].payment.amounts.gross_amount_satang == 35_000


def test_plan_ignores_complimentary_zero_amount_line() -> None:
    zero_line = line(
        "line-zero",
        lineTotalSatang=0,
        serviceSnapshot={
            "serviceId": "companion",
            "variantId": "companion-free",
            "nameTh": "ผู้ติดตาม",
        },
    )
    plan = build_plan(
        [booking()],
        [line(), zero_line],
        evidence(),
        environment="prod",
        authorized_by="admin-001",
        authorization_reference="finance-approval-001",
    )

    assert len(plan.records[0].payment.service_lines) == 1


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"status": "CANCELLED"}, "not an active unpaid"),
        ({"financiallyExcluded": True}, "not an active unpaid"),
        ({"paymentStatus": "PAID"}, "not an active unpaid"),
        ({"grossAmountSatang": 34_999}, "gross amount"),
    ],
)
def test_plan_rejects_ineligible_or_inconsistent_booking(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        build_plan(
            [booking(**overrides)],
            [line()],
            evidence(),
            environment="prod",
            authorized_by="admin-001",
            authorization_reference="finance-approval-001",
        )


def test_test_fixture_requires_explicit_test_only_flag() -> None:
    fixture = {"kind": FIXTURE_KIND}
    with pytest.raises(ValueError, match="allow-test-fixtures"):
        build_plan(
            [booking(testFixture=fixture)],
            [line(testFixture=fixture)],
            evidence(),
            environment="test",
            authorized_by="admin-001",
            authorization_reference="sandbox-batch-001",
        )

    plan = build_plan(
        [booking(testFixture=fixture)],
        [line(testFixture=fixture)],
        evidence(),
        environment="test",
        authorized_by="admin-001",
        authorization_reference="sandbox-batch-001",
        allow_test_fixtures=True,
    )
    assert plan.records[0].test_fixture is True


def test_test_fixture_uses_non_pii_reason_when_discount_text_was_anonymized() -> None:
    fixture = {"kind": FIXTURE_KIND}
    plan = build_plan(
        [
            booking(
                testFixture=fixture,
                subtotalAmountSatang=30_000,
                discountAmountSatang=2_000,
                estimatedAmountSatang=28_000,
                tipAmountSatang=0,
                grossAmountSatang=28_000,
            )
        ],
        [line(testFixture=fixture)],
        evidence(),
        environment="test",
        authorized_by="admin-001",
        authorization_reference="sandbox-batch-001",
        allow_test_fixtures=True,
    )

    assert plan.records[0].payment.discount_reason == "ส่วนลดรายการทดสอบย้อนหลัง"


def test_plan_digest_changes_with_authoritative_paid_time() -> None:
    kwargs = {
        "environment": "prod",
        "authorized_by": "admin-001",
        "authorization_reference": "finance-approval-001",
    }
    first = build_plan([booking()], [line()], evidence(), **kwargs)
    second = build_plan(
        [booking()],
        [line()],
        (
            PaymentEvidence(
                "BK-20260820-001",
                datetime.fromisoformat("2026-08-20T15:00:00+07:00"),
            ),
        ),
        **kwargs,
    )
    assert plan_digest(first) != plan_digest(second)


def test_evidence_csv_requires_timezone_and_rejects_future(tmp_path) -> None:
    evidence_file = tmp_path / "evidence.csv"
    evidence_file.write_text(
        "bookingPublicId,paidAt\nBK-20260820-001,2026-08-20T14:00:00\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="timezone"):
        load_evidence(evidence_file, now=datetime(2026, 9, 2, tzinfo=UTC))

    evidence_file.write_text(
        "bookingPublicId,paidAt\nBK-20260820-001,2026-09-03T14:00:00+07:00\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="future"):
        load_evidence(evidence_file, now=datetime(2026, 9, 2, tzinfo=UTC))


def test_apply_requires_database_and_reviewed_digest() -> None:
    common = [
        "--environment",
        "prod",
        "--evidence-csv",
        "evidence.csv",
        "--authorized-by",
        "admin-001",
        "--authorization-reference",
        "finance-approval-001",
        "--apply",
    ]
    with pytest.raises(SystemExit):
        parse_args([*common, "--confirm-database", "spa-test-db", "--confirm-plan", "x"])
    with pytest.raises(SystemExit):
        parse_args([*common, "--confirm-database", "spa-db"])


def test_prod_rejects_allow_test_fixtures_argument() -> None:
    with pytest.raises(SystemExit):
        parse_args(
            [
                "--environment",
                "prod",
                "--evidence-csv",
                "evidence.csv",
                "--authorized-by",
                "admin-001",
                "--authorization-reference",
                "finance-approval-001",
                "--allow-test-fixtures",
            ]
        )
