#!/usr/bin/env python3
"""Create authorized CASH payments and FlowAccount exports for historical records.

`HISTORICAL_RECORD` is only a service/amount snapshot. It is deliberately not
payment evidence. This migration therefore requires a reviewed CSV containing
an authoritative `paidAt` timestamp for every Booking and records the operator
and authorization reference in an append-only audit event.

Dry-run is the default. Apply is one atomic Firestore batch and requires the
exact database name and plan digest printed by the dry-run.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from app.core.types import CashSettlementStatus, PaymentSource, PaymentStatus
from app.domains.accounting.factory import build_accounting_export
from app.domains.accounting.models import AccountingExport
from app.domains.payments.models import Payment, ServiceLineSnapshot
from app.infrastructure.firestore_payments import (
    _export_data,
    _new_payment,
    _payment_data,
    _with_tip,
)

DEFAULT_PROJECT = "the49-487609"
DATABASES = {"test": "spa-test-db", "prod": "spa-db"}
FIXTURE_KIND = "ANONYMIZED_PRODUCTION_BOOKING"
MIGRATION_VERSION = "BACKFILL_HISTORICAL_CASH_PAYMENTS_V1"
MAX_ATOMIC_WRITES = 450
QUERY_CHUNK_SIZE = 30


@dataclass(frozen=True)
class SourceDocument:
    document_id: str
    data: Mapping[str, Any]


@dataclass(frozen=True)
class PaymentEvidence:
    booking_public_id: str
    paid_at: datetime


@dataclass(frozen=True)
class PlannedRecord:
    booking_doc_id: str
    booking_public_id: str
    payment: Payment
    export: AccountingExport
    test_fixture: bool


@dataclass(frozen=True)
class BackfillPlan:
    environment: str
    database: str
    authorized_by: str
    authorization_reference: str
    records: tuple[PlannedRecord, ...]

    @property
    def write_count(self) -> int:
        # Payment + export + Booking projection + audit, plus the run manifest.
        return len(self.records) * 4 + 1

    @property
    def gross_amount_satang(self) -> int:
        return sum(record.payment.amounts.gross_amount_satang for record in self.records)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=sorted(DATABASES), required=True)
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--evidence-csv", type=Path, required=True)
    parser.add_argument("--authorized-by", required=True)
    parser.add_argument("--authorization-reference", required=True)
    parser.add_argument(
        "--allow-test-fixtures",
        action="store_true",
        help="Allow anonymized production copies in Test only",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-database")
    parser.add_argument("--confirm-plan")
    args = parser.parse_args(argv)
    validate_args(args, parser.error)
    return args


def validate_args(args: argparse.Namespace, fail: Callable[[str], Any]) -> None:
    database = DATABASES[args.environment]
    if not args.authorized_by.strip():
        fail("--authorized-by must identify the approving Admin")
    if not args.authorization_reference.strip():
        fail("--authorization-reference is required for the audit trail")
    if args.allow_test_fixtures and args.environment != "test":
        fail("--allow-test-fixtures is valid only for the Test environment")
    if args.apply and args.confirm_database != database:
        fail(f"--apply requires --confirm-database {database}")
    if args.apply and not args.confirm_plan:
        fail("--apply requires --confirm-plan from the reviewed dry-run")
    if not args.apply and (args.confirm_database or args.confirm_plan):
        fail("confirmation arguments are only valid with --apply")


def _parse_timestamp(value: str, *, row_number: int) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        timestamp = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ValueError(f"row {row_number}: paidAt must be ISO-8601") from error
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(f"row {row_number}: paidAt must include a timezone offset")
    return timestamp


def load_evidence(path: Path, *, now: datetime | None = None) -> tuple[PaymentEvidence, ...]:
    effective_now = now or datetime.now(UTC)
    evidence: list[PaymentEvidence] = []
    seen: set[str] = set()
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or not {"bookingPublicId", "paidAt"}.issubset(
            reader.fieldnames
        ):
            raise ValueError("evidence CSV requires bookingPublicId,paidAt headers")
        for row_number, row in enumerate(reader, start=2):
            booking_public_id = (row.get("bookingPublicId") or "").strip()
            if not booking_public_id:
                raise ValueError(f"row {row_number}: bookingPublicId is required")
            if booking_public_id in seen:
                raise ValueError(f"row {row_number}: duplicate bookingPublicId")
            paid_at = _parse_timestamp(row.get("paidAt") or "", row_number=row_number)
            if paid_at > effective_now:
                raise ValueError(f"row {row_number}: paidAt cannot be in the future")
            seen.add(booking_public_id)
            evidence.append(PaymentEvidence(booking_public_id, paid_at))
    if not evidence:
        raise ValueError("evidence CSV has no payment rows")
    return tuple(sorted(evidence, key=lambda item: item.booking_public_id))


def _fixture_kind(data: Mapping[str, Any]) -> str:
    fixture = data.get("testFixture")
    if not isinstance(fixture, Mapping):
        return ""
    return str(fixture.get("kind", ""))


def _service_lines(
    booking_doc_id: str,
    line_items: Sequence[SourceDocument],
    *,
    expected_fixture_kind: str,
) -> tuple[ServiceLineSnapshot, ...]:
    result: list[ServiceLineSnapshot] = []
    for line_item in line_items:
        data = line_item.data
        if str(data.get("bookingDocId", "")) != booking_doc_id:
            continue
        if data.get("financiallyExcluded") is not False:
            raise ValueError("eligible historical Booking has an excluded line item")
        if _fixture_kind(data) != expected_fixture_kind:
            raise ValueError("Booking and line-item fixture markers do not match")
        service = data.get("serviceSnapshot")
        if not isinstance(service, Mapping):
            raise ValueError("Booking line item has no service snapshot")
        name = service.get("nameTh") or service.get("nameEn")
        sku = service.get("variantId") or service.get("serviceId")
        quantity = data.get("quantity")
        line_total = data.get("lineTotalSatang")
        if not isinstance(name, str) or not name.strip() or not isinstance(sku, str) or not sku:
            raise ValueError("Booking line-item identity is invalid")
        if line_total == 0:
            # Match the live payment projection: complimentary lines are kept
            # on the Booking but are not payable FlowAccount service lines.
            continue
        if (
            isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or quantity <= 0
            or isinstance(line_total, bool)
            or not isinstance(line_total, int)
            or line_total <= 0
            or line_total % quantity
        ):
            raise ValueError("Booking line-item amount is invalid")
        result.append(ServiceLineSnapshot(sku, name, quantity, line_total // quantity))
    result.sort(key=lambda item: (item.sku, item.name))
    if not result:
        raise ValueError("eligible historical Booking has no payable line items")
    return tuple(result)


def build_plan(
    bookings: Sequence[SourceDocument],
    line_items: Sequence[SourceDocument],
    evidence: Sequence[PaymentEvidence],
    *,
    environment: str,
    authorized_by: str,
    authorization_reference: str,
    allow_test_fixtures: bool = False,
) -> BackfillPlan:
    database = DATABASES[environment]
    bookings_by_public_id: dict[str, SourceDocument] = {}
    for booking in bookings:
        public_id = str(booking.data.get("publicBookingId", ""))
        if public_id in bookings_by_public_id:
            raise ValueError("duplicate public Booking ID in Firestore")
        bookings_by_public_id[public_id] = booking

    records: list[PlannedRecord] = []
    for item in evidence:
        booking = bookings_by_public_id.get(item.booking_public_id)
        if booking is None:
            raise ValueError("evidence references a Booking that does not exist")
        data = booking.data
        fixture_kind = _fixture_kind(data)
        is_fixture = bool(fixture_kind)
        if is_fixture and fixture_kind != FIXTURE_KIND:
            raise ValueError("unsupported test fixture kind")
        if is_fixture and not (environment == "test" and allow_test_fixtures):
            raise ValueError(
                "anonymized Test fixtures require --allow-test-fixtures"
            )
        if (
            data.get("status") != "RECORDED"
            or data.get("adminEntryMode") != "HISTORICAL_RECORD"
            or data.get("historicalFinancialRecord") is not True
            or data.get("financiallyExcluded") is not False
            or data.get("paymentStatus") != "UNAVAILABLE"
        ):
            raise ValueError("Booking is not an active unpaid historical financial record")

        lines = _service_lines(
            booking.document_id,
            line_items,
            expected_fixture_kind=fixture_kind,
        )
        payment_source = dict(data)
        if (
            is_fixture
            and int(payment_source.get("discountAmountSatang", 0)) > 0
            and not str(payment_source.get("discountReason", "")).strip()
        ):
            # The anonymized copy intentionally strips free-text discount
            # reasons. Use a non-PII Sandbox-only replacement so the immutable
            # payment snapshot still satisfies the discount invariant.
            payment_source["discountReason"] = "ส่วนลดรายการทดสอบย้อนหลัง"
        payment = _new_payment(booking.document_id, payment_source, lines)
        tip = data.get("tipAmountSatang", 0)
        gross = data.get("grossAmountSatang")
        if isinstance(tip, bool) or not isinstance(tip, int) or tip < 0:
            raise ValueError("historical tip amount is invalid")
        payment = _with_tip(payment, tip)
        # Older historical records predate the gross snapshot field. The
        # canonical payment model can safely derive it from net service + tip;
        # an existing, conflicting gross value is still a hard failure.
        if gross is not None and (
            isinstance(gross, bool)
            or not isinstance(gross, int)
            or gross != payment.amounts.gross_amount_satang
        ):
            raise ValueError("historical gross amount does not match service plus tip")
        paid = payment.mark_paid(
            source=PaymentSource.CASH,
            paid_at=item.paid_at,
            cash_received_by=authorized_by,
        )
        # Old branch-cash settlement evidence is unknown. REVIEW prevents these
        # payments from silently entering the current unsettled-cash deposit flow.
        paid = replace(paid, cash_settlement_status=CashSettlementStatus.REVIEW)
        records.append(
            PlannedRecord(
                booking_doc_id=booking.document_id,
                booking_public_id=item.booking_public_id,
                payment=paid,
                export=build_accounting_export(paid),
                test_fixture=is_fixture,
            )
        )

    plan = BackfillPlan(
        environment=environment,
        database=database,
        authorized_by=authorized_by,
        authorization_reference=authorization_reference,
        records=tuple(sorted(records, key=lambda item: item.booking_public_id)),
    )
    if plan.write_count > MAX_ATOMIC_WRITES:
        maximum = (MAX_ATOMIC_WRITES - 1) // 4
        raise ValueError(
            f"plan requires {plan.write_count} atomic writes; split the evidence CSV "
            f"into at most {maximum} Bookings per run"
        )
    return plan


def plan_digest(plan: BackfillPlan) -> str:
    payload = {
        "migration": MIGRATION_VERSION,
        "environment": plan.environment,
        "database": plan.database,
        "authorizedBy": plan.authorized_by,
        "authorizationReference": plan.authorization_reference,
        "records": [
            {
                "bookingDocId": record.booking_doc_id,
                "bookingPublicId": record.booking_public_id,
                "paymentId": record.payment.payment_id,
                "exportId": record.export.export_id,
                "paidAt": record.payment.paid_at.isoformat()
                if record.payment.paid_at
                else None,
                "serviceAmountSatang": record.payment.amounts.service_amount_satang,
                "tipAmountSatang": record.payment.amounts.tip_amount_satang,
                "grossAmountSatang": record.payment.amounts.gross_amount_satang,
                "testFixture": record.test_fixture,
            }
            for record in plan.records
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _chunks(values: Sequence[str]) -> list[Sequence[str]]:
    return [
        values[offset : offset + QUERY_CHUNK_SIZE]
        for offset in range(0, len(values), QUERY_CHUNK_SIZE)
    ]


def _load_by_query(
    client: firestore.Client,
    *,
    collection: str,
    field: str,
    values: Sequence[str],
) -> list[SourceDocument]:
    result: list[SourceDocument] = []
    for chunk in _chunks(values):
        snapshots = client.collection(collection).where(
            filter=FieldFilter(field, "in", list(chunk))
        ).stream()
        result.extend(
            SourceDocument(snapshot.id, snapshot.to_dict() or {})
            for snapshot in snapshots
        )
    return result


def load_plan(
    client: firestore.Client,
    evidence: Sequence[PaymentEvidence],
    *,
    environment: str,
    authorized_by: str,
    authorization_reference: str,
    allow_test_fixtures: bool,
) -> BackfillPlan:
    public_ids = [item.booking_public_id for item in evidence]
    bookings = _load_by_query(
        client,
        collection="bookings",
        field="publicBookingId",
        values=public_ids,
    )
    booking_ids = [booking.document_id for booking in bookings]
    line_items = _load_by_query(
        client,
        collection="booking_line_items",
        field="bookingDocId",
        values=booking_ids,
    )
    plan = build_plan(
        bookings,
        line_items,
        evidence,
        environment=environment,
        authorized_by=authorized_by,
        authorization_reference=authorization_reference,
        allow_test_fixtures=allow_test_fixtures,
    )
    payment_snapshots = client.get_all(
        [
            client.collection("payments").document(record.payment.payment_id)
            for record in plan.records
        ]
    )
    if any(snapshot.exists for snapshot in payment_snapshots):
        raise RuntimeError("a planned historical Booking already has a Payment")
    export_snapshots = client.get_all(
        [
            client.collection("accounting_exports").document(record.export.export_id)
            for record in plan.records
        ]
    )
    if any(snapshot.exists for snapshot in export_snapshots):
        raise RuntimeError("a planned historical Booking already has an accounting export")
    return plan


def _run_id(plan: BackfillPlan, digest: str) -> str:
    return f"historical-cash-{plan.environment}-{digest[:20]}"


def preflight(client: firestore.Client, plan: BackfillPlan, digest: str) -> str:
    run_id = _run_id(plan, digest)
    if client.collection("migration_runs").document(run_id).get().exists:
        raise RuntimeError(f"migration was already applied: {run_id}")

    booking_snapshots = list(
        client.get_all(
            [
                client.collection("bookings").document(record.booking_doc_id)
                for record in plan.records
            ]
        )
    )
    by_id = {snapshot.id: snapshot for snapshot in booking_snapshots}
    for record in plan.records:
        snapshot = by_id.get(record.booking_doc_id)
        data = snapshot.to_dict() or {} if snapshot is not None else {}
        if (
            snapshot is None
            or not snapshot.exists
            or str(data.get("publicBookingId", "")) != record.booking_public_id
            or data.get("status") != "RECORDED"
            or data.get("financiallyExcluded") is not False
            or data.get("paymentStatus") != "UNAVAILABLE"
        ):
            raise RuntimeError("Booking state changed after the reviewed dry-run")

    payment_snapshots = client.get_all(
        [
            client.collection("payments").document(record.payment.payment_id)
            for record in plan.records
        ]
    )
    export_snapshots = client.get_all(
        [
            client.collection("accounting_exports").document(record.export.export_id)
            for record in plan.records
        ]
    )
    if any(snapshot.exists for snapshot in payment_snapshots) or any(
        snapshot.exists for snapshot in export_snapshots
    ):
        raise RuntimeError("payment/export state changed after the reviewed dry-run")
    return run_id


def apply_plan(
    client: firestore.Client,
    plan: BackfillPlan,
    digest: str,
    *,
    now: datetime | None = None,
) -> str:
    if not plan.records:
        raise RuntimeError("no historical payment evidence was planned")
    effective_now = now or datetime.now(UTC)
    run_id = preflight(client, plan, digest)
    batch = client.batch()
    for record in plan.records:
        payment_data = {
            **_payment_data(record.payment, effective_now),
            "createdAt": effective_now,
            "historicalPaymentBackfill": {
                "runId": run_id,
                "authorizationReference": plan.authorization_reference,
                "cashSettlementDisposition": "REVIEW_REQUIRED",
            },
        }
        export_data = {
            **_export_data(record.export, effective_now),
            "historicalPaymentBackfillRunId": run_id,
        }
        batch.create(
            client.collection("payments").document(record.payment.payment_id),
            payment_data,
        )
        batch.create(
            client.collection("accounting_exports").document(record.export.export_id),
            export_data,
        )
        batch.update(
            client.collection("bookings").document(record.booking_doc_id),
            {
                "paymentStatus": PaymentStatus.PAID,
                "tipAmountSatang": record.payment.amounts.tip_amount_satang,
                "grossAmountSatang": record.payment.amounts.gross_amount_satang,
                "amountDueSatang": 0,
                "paidAmountSatang": record.payment.amounts.gross_amount_satang,
                "paymentUpdatedAt": effective_now,
                "historicalPaymentBackfillRunId": run_id,
            },
        )
        audit_id = hashlib.sha256(
            f"{run_id}:{record.booking_doc_id}:audit".encode()
        ).hexdigest()
        batch.create(
            client.collection("audit_events").document(audit_id),
            {
                "eventType": "HISTORICAL_CASH_PAYMENT_BACKFILLED",
                "actorType": "ADMIN_USER",
                "actorId": plan.authorized_by,
                "authorizationReference": plan.authorization_reference,
                "branchId": record.payment.branch_id,
                "bookingDocId": record.booking_doc_id,
                "paymentId": record.payment.payment_id,
                "paidAt": record.payment.paid_at,
                "cashSettlementStatus": CashSettlementStatus.REVIEW,
                "testFixture": record.test_fixture,
                "occurredAt": effective_now,
                "createdAt": effective_now,
            },
        )

    batch.create(
        client.collection("migration_runs").document(run_id),
        {
            "migration": MIGRATION_VERSION,
            "environment": plan.environment,
            "database": plan.database,
            "planDigest": digest,
            "authorizedBy": plan.authorized_by,
            "authorizationReference": plan.authorization_reference,
            "paymentSource": PaymentSource.CASH,
            "cashSettlementDisposition": CashSettlementStatus.REVIEW,
            "bookingCount": len(plan.records),
            "grossAmountSatang": plan.gross_amount_satang,
            "testFixtureCount": sum(record.test_fixture for record in plan.records),
            "completedAt": effective_now,
        },
    )
    batch.commit()
    return run_id


def verify(client: firestore.Client, plan: BackfillPlan, run_id: str) -> None:
    payment_snapshots = client.get_all(
        [
            client.collection("payments").document(record.payment.payment_id)
            for record in plan.records
        ]
    )
    invalid_payments = sum(
        1
        for snapshot in payment_snapshots
        if not snapshot.exists
        or (snapshot.to_dict() or {}).get("status") != PaymentStatus.PAID
        or (snapshot.to_dict() or {}).get("cashSettlementStatus")
        != CashSettlementStatus.REVIEW
    )
    export_snapshots = client.get_all(
        [
            client.collection("accounting_exports").document(record.export.export_id)
            for record in plan.records
        ]
    )
    invalid_exports = sum(
        1
        for snapshot in export_snapshots
        if not snapshot.exists
        or (snapshot.to_dict() or {}).get("status") != "READY"
        or (snapshot.to_dict() or {}).get("historicalPaymentBackfillRunId") != run_id
    )
    if invalid_payments or invalid_exports:
        raise RuntimeError(
            "post-write verification failed: "
            f"payments={invalid_payments}, exports={invalid_exports}"
        )


def print_summary(plan: BackfillPlan, digest: str, *, applied: bool) -> None:
    mode = "APPLY" if applied else "DRY-RUN"
    dates = sorted(
        record.export.accounting_date.isoformat() for record in plan.records
    )
    print(f"Mode: {mode} | environment: {plan.environment} | database: {plan.database}")
    print(f"Eligible historical CASH payments: {len(plan.records)}")
    print(f"Accounting date range: {dates[0]} through {dates[-1]}")
    print(f"Gross amount: {plan.gross_amount_satang} satang")
    print(f"Test fixtures: {sum(record.test_fixture for record in plan.records)}")
    print("Cash settlement disposition: REVIEW_REQUIRED")
    print(f"Atomic writes including manifest: {plan.write_count}")
    print(f"Plan digest: {digest}")
    print("No FlowAccount API call is made by this migration")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    evidence = load_evidence(args.evidence_csv)
    database = DATABASES[args.environment]
    client = firestore.Client(project=args.project, database=database)
    plan = load_plan(
        client,
        evidence,
        environment=args.environment,
        authorized_by=args.authorized_by.strip(),
        authorization_reference=args.authorization_reference.strip(),
        allow_test_fixtures=args.allow_test_fixtures,
    )
    digest = plan_digest(plan)
    print_summary(plan, digest, applied=args.apply)
    if not args.apply:
        print("Dry-run complete. No Firestore or FlowAccount writes were made.")
        return 0
    if args.confirm_plan != digest:
        print(f"Refusing apply: current plan digest is {digest}", file=sys.stderr)
        return 2
    run_id = apply_plan(client, plan, digest)
    verify(client, plan, run_id)
    print(f"Migration complete and verified: {run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
