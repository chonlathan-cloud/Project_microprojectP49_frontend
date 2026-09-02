#!/usr/bin/env python3
"""Include anonymized historical Test fixtures in SPA analytics.

Only `ANONYMIZED_PRODUCTION_BOOKING` fixtures in `spa-test-db` are eligible.
The source fixtures are already `RECORDED`; this migration changes their
financial exclusion projection instead of rewriting Booking status. Dry-run is
the default, and apply requires the exact reviewed plan digest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

DEFAULT_PROJECT = "the49-487609"
TEST_DATABASE = "spa-test-db"
FIXTURE_KIND = "ANONYMIZED_PRODUCTION_BOOKING"
MIGRATION_VERSION = "ENABLE_TEST_HISTORICAL_ANALYTICS_V1"
MAX_ATOMIC_WRITES = 450
QUERY_CHUNK_SIZE = 30


@dataclass(frozen=True)
class SourceDocument:
    document_id: str
    data: Mapping[str, Any]


@dataclass(frozen=True)
class AnalyticsPlan:
    from_date: date
    to_date: date
    booking_ids: tuple[str, ...]
    line_item_ids: tuple[str, ...]
    net_service_amount_satang: int

    @property
    def write_count(self) -> int:
        return len(self.booking_ids) + len(self.line_item_ids) + 1


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--database", default=TEST_DATABASE)
    parser.add_argument("--from-date", type=date.fromisoformat, required=True)
    parser.add_argument("--to-date", type=date.fromisoformat, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-database")
    parser.add_argument("--confirm-plan")
    args = parser.parse_args(argv)
    validate_args(args, parser.error)
    return args


def validate_args(args: argparse.Namespace, fail: Callable[[str], Any]) -> None:
    if args.database != TEST_DATABASE:
        fail(f"database must be the SPA Test database: {TEST_DATABASE}")
    if args.from_date > args.to_date:
        fail("--from-date must not be after --to-date")
    if args.apply and args.confirm_database != TEST_DATABASE:
        fail(f"--apply requires --confirm-database {TEST_DATABASE}")
    if args.apply and not args.confirm_plan:
        fail("--apply requires --confirm-plan from the reviewed dry-run")
    if not args.apply and (args.confirm_database or args.confirm_plan):
        fail("confirmation arguments are only valid with --apply")


def _fixture_kind(data: Mapping[str, Any]) -> str:
    fixture = data.get("testFixture")
    if not isinstance(fixture, Mapping):
        return ""
    return str(fixture.get("kind", ""))


def _in_range(data: Mapping[str, Any], from_date: date, to_date: date) -> bool:
    try:
        local_date = date.fromisoformat(str(data.get("localDate", "")))
    except ValueError:
        return False
    return from_date <= local_date <= to_date


def build_plan(
    bookings: Sequence[SourceDocument],
    line_items: Sequence[SourceDocument],
    *,
    from_date: date,
    to_date: date,
) -> AnalyticsPlan:
    eligible_bookings: dict[str, SourceDocument] = {}
    for booking in bookings:
        data = booking.data
        if _fixture_kind(data) != FIXTURE_KIND or not _in_range(data, from_date, to_date):
            continue
        if data.get("status") != "RECORDED":
            continue
        if data.get("adminEntryMode") != "HISTORICAL_RECORD":
            continue
        if data.get("historicalFinancialRecord") is not True:
            continue
        if data.get("financiallyExcluded") is not True:
            continue
        eligible_bookings[booking.document_id] = booking

    related_lines: dict[str, list[SourceDocument]] = {
        booking_id: [] for booking_id in eligible_bookings
    }
    for line_item in line_items:
        booking_id = str(line_item.data.get("bookingDocId", ""))
        if booking_id not in related_lines:
            continue
        if _fixture_kind(line_item.data) != FIXTURE_KIND:
            raise ValueError(
                "eligible historical fixture has a non-fixture Booking line item"
            )
        related_lines[booking_id].append(line_item)

    missing_lines = [
        booking_id for booking_id, items in related_lines.items() if not items
    ]
    if missing_lines:
        raise ValueError(
            f"{len(missing_lines)} eligible historical fixtures have no Booking line items"
        )

    booking_ids = tuple(sorted(eligible_bookings))
    line_item_ids = tuple(
        sorted(item.document_id for items in related_lines.values() for item in items)
    )
    plan = AnalyticsPlan(
        from_date=from_date,
        to_date=to_date,
        booking_ids=booking_ids,
        line_item_ids=line_item_ids,
        net_service_amount_satang=sum(
            int(document.data.get("estimatedAmountSatang", 0))
            for document in eligible_bookings.values()
        ),
    )
    if plan.write_count > MAX_ATOMIC_WRITES:
        raise ValueError(
            f"plan requires {plan.write_count} atomic writes; narrow the date range "
            f"to at most {MAX_ATOMIC_WRITES} writes"
        )
    return plan


def plan_digest(plan: AnalyticsPlan) -> str:
    payload = {
        "migration": MIGRATION_VERSION,
        "database": TEST_DATABASE,
        "fromDate": plan.from_date.isoformat(),
        "toDate": plan.to_date.isoformat(),
        "bookingIds": plan.booking_ids,
        "lineItemIds": plan.line_item_ids,
        "netServiceAmountSatang": plan.net_service_amount_satang,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _chunks(values: Sequence[str]) -> list[Sequence[str]]:
    return [
        values[offset : offset + QUERY_CHUNK_SIZE]
        for offset in range(0, len(values), QUERY_CHUNK_SIZE)
    ]


def load_plan(
    client: firestore.Client, *, from_date: date, to_date: date
) -> AnalyticsPlan:
    booking_snapshots = client.collection("bookings").where(
        filter=FieldFilter("testFixture.kind", "==", FIXTURE_KIND)
    ).stream()
    bookings = [
        SourceDocument(snapshot.id, snapshot.to_dict() or {})
        for snapshot in booking_snapshots
    ]
    candidate_ids = [
        booking.document_id
        for booking in bookings
        if _in_range(booking.data, from_date, to_date)
        and booking.data.get("financiallyExcluded") is True
    ]
    line_items: list[SourceDocument] = []
    for chunk in _chunks(candidate_ids):
        snapshots = client.collection("booking_line_items").where(
            filter=FieldFilter("bookingDocId", "in", list(chunk))
        ).stream()
        line_items.extend(
            SourceDocument(snapshot.id, snapshot.to_dict() or {})
            for snapshot in snapshots
        )
    return build_plan(
        bookings,
        line_items,
        from_date=from_date,
        to_date=to_date,
    )


def _run_id(plan: AnalyticsPlan, digest: str) -> str:
    return (
        f"enable-test-historical-analytics-{plan.from_date.strftime('%Y%m%d')}-"
        f"{plan.to_date.strftime('%Y%m%d')}-{digest[:12]}"
    )


def preflight(client: firestore.Client, plan: AnalyticsPlan, digest: str) -> str:
    run_id = _run_id(plan, digest)
    if client.collection("migration_runs").document(run_id).get().exists:
        raise RuntimeError(f"migration was already applied: {run_id}")

    booking_snapshots = client.get_all(
        [client.collection("bookings").document(item) for item in plan.booking_ids]
    )
    for snapshot in booking_snapshots:
        data = snapshot.to_dict() or {}
        if (
            not snapshot.exists
            or _fixture_kind(data) != FIXTURE_KIND
            or data.get("status") != "RECORDED"
            or data.get("financiallyExcluded") is not True
        ):
            raise RuntimeError("Booking fixture state changed after the reviewed dry-run")

    line_snapshots = client.get_all(
        [
            client.collection("booking_line_items").document(item)
            for item in plan.line_item_ids
        ]
    )
    for snapshot in line_snapshots:
        data = snapshot.to_dict() or {}
        if not snapshot.exists or _fixture_kind(data) != FIXTURE_KIND:
            raise RuntimeError("Booking line fixture state changed after the reviewed dry-run")
    return run_id


def apply_plan(
    client: firestore.Client, plan: AnalyticsPlan, digest: str
) -> str:
    if not plan.booking_ids:
        raise RuntimeError("no excluded historical Test fixtures matched the date range")
    run_id = preflight(client, plan, digest)
    batch = client.batch()
    common_update = {
        "financiallyExcluded": False,
        "testAnalyticsEnabled": True,
        "testAnalyticsEnabledAt": firestore.SERVER_TIMESTAMP,
        "testAnalyticsEnabledRunId": run_id,
    }
    for document_id in plan.booking_ids:
        batch.update(client.collection("bookings").document(document_id), common_update)
    for document_id in plan.line_item_ids:
        batch.update(
            client.collection("booking_line_items").document(document_id),
            common_update,
        )
    batch.create(
        client.collection("migration_runs").document(run_id),
        {
            "migration": MIGRATION_VERSION,
            "database": TEST_DATABASE,
            "fixtureKind": FIXTURE_KIND,
            "fromLocalDate": plan.from_date.isoformat(),
            "toLocalDate": plan.to_date.isoformat(),
            "planDigest": digest,
            "bookingCount": len(plan.booking_ids),
            "lineItemCount": len(plan.line_item_ids),
            "netServiceAmountSatang": plan.net_service_amount_satang,
            "completedAt": firestore.SERVER_TIMESTAMP,
        },
    )
    batch.commit()
    return run_id


def verify(client: firestore.Client, plan: AnalyticsPlan, run_id: str) -> None:
    snapshots = client.get_all(
        [client.collection("bookings").document(item) for item in plan.booking_ids]
    )
    invalid = 0
    for snapshot in snapshots:
        data = snapshot.to_dict() or {}
        if (
            not snapshot.exists
            or data.get("financiallyExcluded") is not False
            or data.get("testAnalyticsEnabledRunId") != run_id
        ):
            invalid += 1
    if invalid:
        raise RuntimeError(f"post-write verification failed for {invalid} Bookings")


def print_summary(plan: AnalyticsPlan, digest: str, *, applied: bool) -> None:
    mode = "APPLY" if applied else "DRY-RUN"
    print(f"Mode: {mode} | database: {TEST_DATABASE}")
    print(f"Fixture kind: {FIXTURE_KIND}")
    print(
        f"Historical range: {plan.from_date.isoformat()} through "
        f"{plan.to_date.isoformat()}"
    )
    print(f"Eligible RECORDED Bookings: {len(plan.booking_ids)}")
    print(f"Related Booking line items: {len(plan.line_item_ids)}")
    print(f"Net service amount: {plan.net_service_amount_satang} satang")
    print(f"Atomic writes including manifest: {plan.write_count}")
    print(f"Plan digest: {digest}")
    print("Customer identity and health data: not printed or changed")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    client = firestore.Client(project=args.project, database=args.database)
    plan = load_plan(client, from_date=args.from_date, to_date=args.to_date)
    digest = plan_digest(plan)
    print_summary(plan, digest, applied=args.apply)
    if not args.apply:
        print("Dry-run complete. No writes were made.")
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
