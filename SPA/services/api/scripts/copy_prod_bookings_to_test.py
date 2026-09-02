#!/usr/bin/env python3
"""Copy anonymized historical SPA bookings from Production to Test Firestore.

The Production database is read-only. The Test write is create-only and atomic,
includes a migration manifest, and excludes identity, health, consent, payment,
accounting, audit, notification, idempotency, and capacity-consumption records.
Dry-run is the default.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from google.cloud.firestore_v1.document import DocumentReference

DEFAULT_PROJECT = "the49-487609"
PRODUCTION_DATABASE = "spa-db"
TEST_DATABASE = "spa-test-db"
MIGRATION_VERSION = "COPY_ANONYMIZED_PROD_BOOKINGS_TO_TEST_V1"
MAX_ATOMIC_WRITES = 450
QUERY_CHUNK_SIZE = 30
BOOKING_PRESERVED_FIELDS = (
    "branchId",
    "serviceName",
    "serviceId",
    "serviceNameTh",
    "serviceNameEn",
    "serviceNamesTh",
    "serviceNamesEn",
    "startAt",
    "endAt",
    "localDate",
    "localStartTime",
    "timezone",
    "pax",
    "subtotalAmountSatang",
    "discountAmountSatang",
    "estimatedAmountSatang",
    "tipAmountSatang",
    "grossAmountSatang",
    "priceIncludesVat",
    "version",
    "createdAt",
    "updatedAt",
    "recordedAt",
)
SERVICE_SNAPSHOT_FIELDS = (
    "serviceId",
    "variantId",
    "nameTh",
    "nameEn",
    "durationMinutes",
    "pricingMode",
    "requiredPax",
    "unitPriceSatang",
)
FORBIDDEN_KEYS = frozenset(
    {
        "actorId",
        "actorIdHash",
        "capturedByActorId",
        "confirmedBy",
        "discountAppliedBy",
        "lineIdentityHash",
        "lineUserId",
        "phoneE164",
        "phoneMasked",
        "recordedBy",
        "statusToken",
        "statusTokenHash",
        "therapistId",
    }
)


@dataclass(frozen=True)
class SourceDocument:
    document_id: str
    data: Mapping[str, Any]


@dataclass(frozen=True)
class PlannedWrite:
    collection: str
    document_id: str
    data: Mapping[str, Any]

    @property
    def path(self) -> str:
        return f"{self.collection}/{self.document_id}"


@dataclass(frozen=True)
class CopyPlan:
    run_id: str
    from_date: date
    to_date: date
    writes: tuple[PlannedWrite, ...]
    source_booking_ids: tuple[str, ...]

    @property
    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for write in self.writes:
            counts[write.collection] += 1
        return dict(sorted(counts.items()))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--source-database", default=PRODUCTION_DATABASE)
    parser.add_argument("--target-database", default=TEST_DATABASE)
    parser.add_argument("--from-date", type=date.fromisoformat, required=True)
    parser.add_argument("--to-date", type=date.fromisoformat, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-target")
    parser.add_argument("--confirm-plan")
    args = parser.parse_args(argv)
    validate_args(args, parser.error)
    return args


def validate_args(args: argparse.Namespace, fail: Callable[[str], Any]) -> None:
    if args.source_database != PRODUCTION_DATABASE:
        fail(f"source must be the SPA Production database: {PRODUCTION_DATABASE}")
    if args.target_database != TEST_DATABASE:
        fail(f"target must be the SPA Test database: {TEST_DATABASE}")
    if args.source_database == args.target_database:
        fail("source and target databases must differ")
    if args.from_date > args.to_date:
        fail("--from-date must not be after --to-date")
    today = datetime.now(ZoneInfo("Asia/Bangkok")).date()
    if args.to_date >= today:
        fail(f"--to-date must be historical (before {today.isoformat()})")
    if args.apply and args.confirm_target != args.target_database:
        fail("--apply requires --confirm-target matching --target-database exactly")
    if args.apply and not args.confirm_plan:
        fail("--apply requires --confirm-plan from the reviewed dry-run")
    if not args.apply and (args.confirm_target or args.confirm_plan):
        fail("confirmation arguments are only valid with --apply")


def _chunks(values: Sequence[str], size: int = QUERY_CHUNK_SIZE) -> Iterable[Sequence[str]]:
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


def _stable_id(run_id: str, kind: str, source_id: str) -> str:
    digest = hashlib.sha256(f"{run_id}:{kind}:{source_id}".encode()).hexdigest()
    return f"tst_{kind}_{digest[:24]}"


def _public_booking_id(run_id: str, local_date: str, source_id: str) -> str:
    digest = hashlib.sha256(f"{run_id}:public:{source_id}".encode()).hexdigest()[:10].upper()
    return f"BK-TST-{local_date.replace('-', '')}-{digest}"


def _copy_keys(data: Mapping[str, Any], keys: Sequence[str]) -> dict[str, Any]:
    return {key: data[key] for key in keys if key in data}


def _source_hash(source_id: str) -> str:
    return hashlib.sha256(source_id.encode()).hexdigest()


def _fixture_metadata(run_id: str, source_id: str) -> dict[str, str]:
    return {
        "kind": "ANONYMIZED_PRODUCTION_BOOKING",
        "migrationRunId": run_id,
        "sourceDocumentIdHash": _source_hash(source_id),
    }


def _assert_no_forbidden_keys(value: Any, *, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key) in FORBIDDEN_KEYS:
                raise ValueError(f"forbidden identity field in generated fixture: {path}.{key}")
            _assert_no_forbidden_keys(nested, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _assert_no_forbidden_keys(nested, path=f"{path}[{index}]")


def build_plan(
    bookings: Sequence[SourceDocument],
    line_items: Sequence[SourceDocument],
    participants: Sequence[SourceDocument],
    *,
    from_date: date,
    to_date: date,
    run_id: str,
) -> CopyPlan:
    if not bookings:
        raise ValueError("no Production bookings matched the requested historical date range")

    booking_ids = {document.document_id for document in bookings}
    if len(booking_ids) != len(bookings):
        raise ValueError("duplicate Production booking document IDs")

    lines_by_booking: dict[str, list[SourceDocument]] = defaultdict(list)
    for document in line_items:
        booking_id = str(document.data.get("bookingDocId", ""))
        if booking_id not in booking_ids:
            raise ValueError(f"orphan line item in selected source data: {document.document_id}")
        lines_by_booking[booking_id].append(document)

    participants_by_booking: dict[str, list[SourceDocument]] = defaultdict(list)
    for document in participants:
        booking_id = str(document.data.get("bookingDocId", ""))
        if booking_id not in booking_ids:
            raise ValueError(f"orphan participant in selected source data: {document.document_id}")
        participants_by_booking[booking_id].append(document)

    booking_id_map = {
        source_id: _stable_id(run_id, "booking", source_id) for source_id in sorted(booking_ids)
    }
    participant_id_map = {
        document.document_id: _stable_id(run_id, "participant", document.document_id)
        for document in participants
    }

    writes: list[PlannedWrite] = []
    for booking in sorted(bookings, key=lambda item: item.document_id):
        source = booking.data
        source_local_date = str(source.get("localDate", ""))
        try:
            parsed_local_date = date.fromisoformat(source_local_date)
        except ValueError as error:
            raise ValueError(
                f"invalid localDate on source booking {booking.document_id}"
            ) from error
        if not from_date <= parsed_local_date <= to_date:
            raise ValueError(f"source booking outside requested date range: {booking.document_id}")
        if not lines_by_booking[booking.document_id]:
            raise ValueError(f"source booking has no line items: {booking.document_id}")
        if not participants_by_booking[booking.document_id]:
            raise ValueError(f"source booking has no participants: {booking.document_id}")

        target_booking_id = booking_id_map[booking.document_id]
        booking_data = _copy_keys(source, BOOKING_PRESERVED_FIELDS)
        booking_data.update(
            {
                "publicBookingId": _public_booking_id(
                    run_id, source_local_date, booking.document_id
                ),
                "source": "ADMIN_WEB",
                "status": "RECORDED",
                "customerListBucket": "HISTORY",
                "contact": {"mode": "NONE"},
                "adminEntryMode": "HISTORICAL_RECORD",
                "customerName": f"Test Guest {_source_hash(booking.document_id)[:6].upper()}",
                "paymentStatus": "UNAVAILABLE",
                "financiallyExcluded": True,
                "historicalFinancialRecord": True,
                "healthAlert": False,
                "assignmentState": "NOT_REQUIRED",
                "capacityReleased": True,
                "testFixture": _fixture_metadata(run_id, booking.document_id),
            }
        )
        writes.append(PlannedWrite("bookings", target_booking_id, booking_data))

        booking_participants = sorted(
            participants_by_booking[booking.document_id],
            key=lambda item: (int(item.data.get("sequence", 0)), item.document_id),
        )
        for participant in booking_participants:
            target_participant_id = participant_id_map[participant.document_id]
            target_health_id = _stable_id(run_id, "health", participant.document_id)
            participant_data = {
                "bookingDocId": target_booking_id,
                "branchId": source.get("branchId", participant.data.get("branchId")),
                "sequence": int(participant.data.get("sequence", 0)),
                "nickname": (
                    f"Test Guest {_source_hash(participant.document_id)[:6].upper()}"
                ),
                "healthAlert": False,
                "healthProfileId": target_health_id,
                "createdAt": participant.data.get("createdAt", source.get("createdAt")),
                "testFixture": _fixture_metadata(run_id, participant.document_id),
            }
            writes.append(
                PlannedWrite("booking_participants", target_participant_id, participant_data)
            )
            health_data = {
                "bookingDocId": target_booking_id,
                "participantId": target_participant_id,
                "hasInformation": False,
                "details": "",
                "policyVersion": "TEST_FIXTURE_NO_HEALTH_DATA_V1",
                "createdAt": participant.data.get("createdAt", source.get("createdAt")),
                "updatedAt": participant.data.get("createdAt", source.get("updatedAt")),
                "testFixture": _fixture_metadata(run_id, participant.document_id),
            }
            writes.append(PlannedWrite("health_profiles", target_health_id, health_data))

        for line_item in sorted(
            lines_by_booking[booking.document_id], key=lambda item: item.document_id
        ):
            participant_ids = line_item.data.get("participantIds", [])
            if not isinstance(participant_ids, list) or not participant_ids:
                raise ValueError(f"source line item has no participantIds: {line_item.document_id}")
            unknown = [item for item in participant_ids if str(item) not in participant_id_map]
            if unknown:
                raise ValueError(
                    "source line item references participant outside selection: "
                    f"{line_item.document_id}"
                )
            source_snapshot = line_item.data.get("serviceSnapshot") or {}
            if not isinstance(source_snapshot, Mapping):
                raise ValueError(f"invalid serviceSnapshot: {line_item.document_id}")
            line_data = {
                "bookingDocId": target_booking_id,
                "branchId": source.get("branchId", line_item.data.get("branchId")),
                "serviceSnapshot": _copy_keys(source_snapshot, SERVICE_SNAPSHOT_FIELDS),
                "quantity": int(line_item.data.get("quantity", 1)),
                "lineTotalSatang": int(line_item.data.get("lineTotalSatang", 0)),
                "financiallyExcluded": True,
                "participantIds": [participant_id_map[str(item)] for item in participant_ids],
                "createdAt": line_item.data.get("createdAt", source.get("createdAt")),
                "testFixture": _fixture_metadata(run_id, line_item.document_id),
            }
            writes.append(
                PlannedWrite(
                    "booking_line_items",
                    _stable_id(run_id, "line", line_item.document_id),
                    line_data,
                )
            )

    paths = [write.path for write in writes]
    if len(paths) != len(set(paths)):
        raise ValueError("generated Test document IDs are not unique")
    if len(writes) + 1 > MAX_ATOMIC_WRITES:
        raise ValueError(
            f"plan requires {len(writes) + 1} atomic writes including manifest; "
            f"maximum is {MAX_ATOMIC_WRITES}"
        )
    for write in writes:
        _assert_no_forbidden_keys(write.data, path=write.path)
    return CopyPlan(
        run_id=run_id,
        from_date=from_date,
        to_date=to_date,
        writes=tuple(writes),
        source_booking_ids=tuple(sorted(booking_ids)),
    )


def _digest_value(value: Any) -> Any:
    if isinstance(value, DocumentReference):
        return {"type": "reference", "value": value.path}
    if isinstance(value, datetime):
        return {"type": "datetime", "value": value.isoformat()}
    if isinstance(value, date):
        return {"type": "date", "value": value.isoformat()}
    if isinstance(value, bytes):
        return {"type": "bytes", "value": base64.b64encode(value).decode("ascii")}
    if isinstance(value, Mapping):
        return {str(key): _digest_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_digest_value(item) for item in value]
    return value


def plan_digest(plan: CopyPlan) -> str:
    content = [
        {"path": write.path, "data": _digest_value(write.data)} for write in plan.writes
    ]
    encoded = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _read_bookings(
    client: firestore.Client, *, from_date: date, to_date: date
) -> list[SourceDocument]:
    query = (
        client.collection("bookings")
        .where(filter=FieldFilter("localDate", ">=", from_date.isoformat()))
        .where(filter=FieldFilter("localDate", "<=", to_date.isoformat()))
        .order_by("localDate")
    )
    return [
        SourceDocument(snapshot.id, snapshot.to_dict() or {}) for snapshot in query.stream()
    ]


def _read_related(
    client: firestore.Client, collection: str, booking_ids: Sequence[str]
) -> list[SourceDocument]:
    documents: list[SourceDocument] = []
    for chunk in _chunks(booking_ids):
        query = client.collection(collection).where(
            filter=FieldFilter("bookingDocId", "in", list(chunk))
        )
        documents.extend(
            SourceDocument(snapshot.id, snapshot.to_dict() or {}) for snapshot in query.stream()
        )
    return documents


def load_plan(
    source: firestore.Client, *, from_date: date, to_date: date, run_id: str
) -> CopyPlan:
    bookings = _read_bookings(source, from_date=from_date, to_date=to_date)
    booking_ids = [document.document_id for document in bookings]
    line_items = _read_related(source, "booking_line_items", booking_ids)
    participants = _read_related(source, "booking_participants", booking_ids)
    return build_plan(
        bookings,
        line_items,
        participants,
        from_date=from_date,
        to_date=to_date,
        run_id=run_id,
    )


def preflight_target(target: firestore.Client, plan: CopyPlan) -> None:
    manifest = target.collection("migration_runs").document(plan.run_id).get()
    if manifest.exists:
        raise RuntimeError(f"migration manifest already exists: {plan.run_id}")

    references = [target.document(write.path) for write in plan.writes]
    collisions = [
        snapshot.reference.path for snapshot in target.get_all(references) if snapshot.exists
    ]
    if collisions:
        raise RuntimeError(
            f"refusing create-only migration: {len(collisions)} target document IDs already exist"
        )

    public_ids = [
        str(write.data["publicBookingId"])
        for write in plan.writes
        if write.collection == "bookings"
    ]
    public_collisions = []
    for chunk in _chunks(public_ids):
        query = target.collection("bookings").where(
            filter=FieldFilter("publicBookingId", "in", list(chunk))
        )
        public_collisions.extend(snapshot.id for snapshot in query.stream())
    if public_collisions:
        raise RuntimeError(
            f"refusing migration: {len(public_collisions)} synthetic public booking IDs collide"
        )


def manifest_data(plan: CopyPlan, digest: str) -> dict[str, Any]:
    return {
        "migration": MIGRATION_VERSION,
        "runId": plan.run_id,
        "sourceDatabase": PRODUCTION_DATABASE,
        "targetDatabase": TEST_DATABASE,
        "fromLocalDate": plan.from_date.isoformat(),
        "toLocalDate": plan.to_date.isoformat(),
        "planDigest": digest,
        "counts": plan.counts,
        "createdDocumentPaths": [write.path for write in plan.writes],
        "sourceBookingDocumentIdHashes": [
            _source_hash(source_id) for source_id in plan.source_booking_ids
        ],
        "completedAt": firestore.SERVER_TIMESTAMP,
    }


def apply_plan(target: firestore.Client, plan: CopyPlan, digest: str) -> None:
    preflight_target(target, plan)
    batch = target.batch()
    for write in plan.writes:
        batch.create(target.document(write.path), dict(write.data))
    batch.create(
        target.collection("migration_runs").document(plan.run_id),
        manifest_data(plan, digest),
    )
    batch.commit()


def verify_target(target: firestore.Client, plan: CopyPlan, digest: str) -> tuple[str, ...]:
    mismatches: list[str] = []
    expected_by_path = {write.path: write for write in plan.writes}
    snapshots = target.get_all([target.document(path) for path in expected_by_path])
    observed_paths: set[str] = set()
    for snapshot in snapshots:
        observed_paths.add(snapshot.reference.path)
        expected = expected_by_path[snapshot.reference.path]
        if not snapshot.exists or _digest_value(snapshot.to_dict() or {}) != _digest_value(
            expected.data
        ):
            mismatches.append(snapshot.reference.path)
    mismatches.extend(sorted(set(expected_by_path) - observed_paths))
    manifest = target.collection("migration_runs").document(plan.run_id).get()
    manifest_value = manifest.to_dict() or {}
    if not manifest.exists or manifest_value.get("planDigest") != digest:
        mismatches.append(f"migration_runs/{plan.run_id}")
    return tuple(sorted(set(mismatches)))


def print_summary(plan: CopyPlan, digest: str, *, applied: bool) -> None:
    mode = "APPLY" if applied else "DRY-RUN"
    print(f"Mode: {mode} | {PRODUCTION_DATABASE} (read-only) -> {TEST_DATABASE} (create-only)")
    print(f"Historical range: {plan.from_date.isoformat()} through {plan.to_date.isoformat()}")
    print(f"Migration run: {plan.run_id}")
    print(f"Plan digest: {digest}")
    print("Document counts: " + json.dumps(plan.counts, sort_keys=True))
    print(f"Atomic writes including manifest: {len(plan.writes) + 1}")
    print("Sensitive identity, health details, payment, accounting, and audit data: excluded")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    run_id = (
        f"prod-bookings-{args.from_date.strftime('%Y%m%d')}-"
        f"{args.to_date.strftime('%Y%m%d')}-v1"
    )
    source = firestore.Client(project=args.project, database=args.source_database)
    target = firestore.Client(project=args.project, database=args.target_database)
    plan = load_plan(source, from_date=args.from_date, to_date=args.to_date, run_id=run_id)
    digest = plan_digest(plan)
    preflight_target(target, plan)
    print_summary(plan, digest, applied=args.apply)

    if not args.apply:
        print("Dry-run complete. No writes were made.")
        return 0
    if args.confirm_plan != digest:
        print(f"Refusing apply: current plan digest is {digest}", file=sys.stderr)
        return 2

    source_count_before = len(plan.source_booking_ids)
    apply_plan(target, plan, digest)
    mismatches = verify_target(target, plan, digest)
    source_count_after = len(
        _read_bookings(source, from_date=args.from_date, to_date=args.to_date)
    )
    if source_count_after != source_count_before:
        print(
            "Production source changed during migration; target was written atomically.",
            file=sys.stderr,
        )
        return 4
    if mismatches:
        print(
            f"Post-write verification failed for {len(mismatches)} Test documents.",
            file=sys.stderr,
        )
        return 3
    print(f"Migration complete and verified: {len(plan.writes)} Test documents created.")
    print("Production booking count for the selected range was unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
