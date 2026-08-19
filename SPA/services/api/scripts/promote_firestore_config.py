#!/usr/bin/env python3
"""Promote allowlisted SPA configuration between named Firestore databases.

Dry-run is the default. The tool never copies identity, booking, health, audit,
notification, idempotency, webhook, or capacity-consumption documents.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from google.cloud import firestore
from google.cloud.firestore_v1.document import DocumentReference

DEFAULT_PROJECT = "the49-487609"
DEFAULT_SOURCE_DATABASE = "spa-test-db"
DEFAULT_TARGET_DATABASE = "spa-db"
CORE_COLLECTIONS = ("branches", "services", "resources")
OPTIONAL_COLLECTIONS = ("therapists", "special_closures")
ALLOWED_COLLECTIONS = frozenset((*CORE_COLLECTIONS, *OPTIONAL_COLLECTIONS))
PROTECTED_COLLECTIONS = (
    "bookings",
    "booking_participants",
    "booking_line_items",
    "health_profiles",
    "consent_evidence",
    "capacity_buckets",
    "booking_idempotency",
    "line_booking_links",
    "notification_outbox",
    "audit_events",
    "admin_commands",
    "line_webhook_events",
    "line_group_candidates",
)
MAX_ATOMIC_WRITES = 400


@dataclass(frozen=True)
class DocumentChange:
    collection: str
    document_id: str
    action: str
    source_data: Mapping[str, Any]
    changed_fields: tuple[str, ...] = ()
    target_data: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class PromotionPlan:
    changes: tuple[DocumentChange, ...]
    source_counts: Mapping[str, int]
    target_protected_nonempty: tuple[str, ...]

    @property
    def writes(self) -> tuple[DocumentChange, ...]:
        return tuple(change for change in self.changes if change.action in {"create", "update"})

    @property
    def conflicts(self) -> tuple[DocumentChange, ...]:
        return tuple(change for change in self.changes if change.action == "conflict")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Promote allowlisted SPA master/config documents to Production Firestore."
    )
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--source-database", default=DEFAULT_SOURCE_DATABASE)
    parser.add_argument("--target-database", default=DEFAULT_TARGET_DATABASE)
    parser.add_argument(
        "--include-therapists",
        action="store_true",
        help="Include verified real therapist records.",
    )
    parser.add_argument(
        "--include-special-closures",
        action="store_true",
        help="Include special closures on or after --closure-from.",
    )
    parser.add_argument(
        "--closure-from",
        type=date.fromisoformat,
        help="Required with --include-special-closures (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--allow-updates",
        action="store_true",
        help="Allow differing target config documents to be replaced.",
    )
    parser.add_argument(
        "--allow-nonempty-production-data",
        action="store_true",
        help="Allow config promotion after Production transactional data exists.",
    )
    parser.add_argument("--apply", action="store_true", help="Commit the planned writes.")
    parser.add_argument(
        "--confirm-target",
        help="Required with --apply and must exactly equal --target-database.",
    )
    parser.add_argument(
        "--confirm-plan",
        help="Required with --apply and must match the reviewed dry-run plan digest.",
    )
    parser.add_argument("--report", type=Path, help="Write a metadata-only JSON report.")
    args = parser.parse_args(argv)
    validate_args(args, parser.error)
    return args


def validate_args(args: argparse.Namespace, fail: Callable[[str], Any]) -> None:
    if args.source_database == args.target_database:
        fail("source and target databases must differ")
    if "(default)" in {args.source_database, args.target_database}:
        fail("the Receipt (default) database is outside the SPA promotion boundary")
    if args.include_special_closures != bool(args.closure_from):
        fail("--include-special-closures and --closure-from must be supplied together")
    if args.apply and args.confirm_target != args.target_database:
        fail("--apply requires --confirm-target matching --target-database exactly")
    if args.apply and not args.confirm_plan:
        fail("--apply requires --confirm-plan from the reviewed dry-run")
    if not args.apply and args.confirm_target:
        fail("--confirm-target is only valid with --apply")
    if not args.apply and args.confirm_plan:
        fail("--confirm-plan is only valid with --apply")


def selected_collections(args: argparse.Namespace) -> tuple[str, ...]:
    collections = list(CORE_COLLECTIONS)
    if args.include_therapists:
        collections.append("therapists")
    if args.include_special_closures:
        collections.append("special_closures")
    if not set(collections) <= ALLOWED_COLLECTIONS:  # defensive invariant
        raise ValueError("promotion requested a non-allowlisted collection")
    return tuple(collections)


def _comparison_value(value: Any) -> Any:
    if isinstance(value, DocumentReference):
        return {"__firestore_reference__": value.path}
    if isinstance(value, dict):
        return {key: _comparison_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_comparison_value(item) for item in value]
    return value


def _equivalent(source: Any, target: Any) -> bool:
    return _comparison_value(source) == _comparison_value(target)


def _digest_value(value: Any) -> Any:
    if isinstance(value, DocumentReference):
        return {"type": "reference", "value": value.path}
    if isinstance(value, datetime):
        return {"type": "datetime", "value": value.isoformat()}
    if isinstance(value, date):
        return {"type": "date", "value": value.isoformat()}
    if isinstance(value, bytes):
        return {"type": "bytes", "value": base64.b64encode(value).decode("ascii")}
    if isinstance(value, dict):
        return {str(key): _digest_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_digest_value(item) for item in value]
    if hasattr(value, "latitude") and hasattr(value, "longitude"):
        return {
            "type": "geo_point",
            "latitude": value.latitude,
            "longitude": value.longitude,
        }
    return value


def plan_digest(plan: PromotionPlan) -> str:
    content = [
        {
            "path": f"{change.collection}/{change.document_id}",
            "action": change.action,
            "source": _digest_value(dict(change.source_data)),
            "target": (
                _digest_value(dict(change.target_data)) if change.target_data is not None else None
            ),
        }
        for change in plan.changes
    ]
    encoded = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _top_level_changed_fields(
    source: Mapping[str, Any], target: Mapping[str, Any]
) -> tuple[str, ...]:
    keys = set(source) | set(target)
    return tuple(sorted(key for key in keys if not _equivalent(source.get(key), target.get(key))))


def _documents(client: firestore.Client, collection: str) -> dict[str, Mapping[str, Any]]:
    return {
        snapshot.id: snapshot.to_dict() or {}
        for snapshot in client.collection(collection).stream()
    }


def _has_documents(client: firestore.Client, collection: str) -> bool:
    return any(client.collection(collection).limit(1).stream())


def build_plan(
    source: firestore.Client,
    target: firestore.Client,
    collections: Iterable[str],
    *,
    allow_updates: bool,
    closure_from: date | None = None,
) -> PromotionPlan:
    selected = tuple(collections)
    if not set(selected) <= ALLOWED_COLLECTIONS:
        invalid = sorted(set(selected) - ALLOWED_COLLECTIONS)
        raise ValueError(f"non-allowlisted collections requested: {', '.join(invalid)}")

    changes: list[DocumentChange] = []
    source_counts: dict[str, int] = {}
    for collection in selected:
        source_documents = _documents(source, collection)
        if collection == "special_closures" and closure_from:
            source_documents = {
                document_id: data
                for document_id, data in source_documents.items()
                if str(data.get("localDate", "")) >= closure_from.isoformat()
            }
        source_counts[collection] = len(source_documents)
        if collection in CORE_COLLECTIONS and not source_documents:
            raise RuntimeError(f"required source collection is empty: {collection}")

        target_documents = _documents(target, collection)
        for document_id, source_data in sorted(source_documents.items()):
            target_data = target_documents.get(document_id)
            if target_data is None:
                action = "create"
                changed_fields = tuple(sorted(source_data))
            elif _equivalent(source_data, target_data):
                action = "unchanged"
                changed_fields = ()
            else:
                action = "update" if allow_updates else "conflict"
                changed_fields = _top_level_changed_fields(source_data, target_data)
            changes.append(
                DocumentChange(
                    collection=collection,
                    document_id=document_id,
                    action=action,
                    source_data=source_data,
                    changed_fields=changed_fields,
                    target_data=target_data,
                )
            )

    protected_nonempty = tuple(
        collection for collection in PROTECTED_COLLECTIONS if _has_documents(target, collection)
    )
    return PromotionPlan(tuple(changes), source_counts, protected_nonempty)


def _retarget_references(value: Any, target: firestore.Client) -> Any:
    if isinstance(value, DocumentReference):
        return target.document(value.path)
    if isinstance(value, dict):
        return {key: _retarget_references(item, target) for key, item in value.items()}
    if isinstance(value, list):
        return [_retarget_references(item, target) for item in value]
    if isinstance(value, tuple):
        return tuple(_retarget_references(item, target) for item in value)
    return value


def apply_plan(target: firestore.Client, plan: PromotionPlan) -> None:
    writes = plan.writes
    if plan.conflicts:
        raise RuntimeError("plan contains unresolved target conflicts")
    if len(writes) > MAX_ATOMIC_WRITES:
        raise RuntimeError(
            f"plan has {len(writes)} writes; refusing non-atomic promotion above "
            f"{MAX_ATOMIC_WRITES}"
        )
    if not writes:
        return
    batch = target.batch()
    for change in writes:
        reference = target.collection(change.collection).document(change.document_id)
        batch.set(reference, _retarget_references(dict(change.source_data), target))
    batch.commit()


def verify_plan(target: firestore.Client, plan: PromotionPlan) -> tuple[str, ...]:
    mismatches: list[str] = []
    for change in plan.writes:
        snapshot = target.collection(change.collection).document(change.document_id).get()
        expected = _retarget_references(dict(change.source_data), target)
        if not snapshot.exists or not _equivalent(snapshot.to_dict() or {}, expected):
            mismatches.append(f"{change.collection}/{change.document_id}")
    return tuple(mismatches)


def report_payload(
    args: argparse.Namespace,
    plan: PromotionPlan,
    *,
    applied: bool,
    verification_mismatches: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "generatedAt": datetime.now().astimezone().isoformat(),
        "project": args.project,
        "sourceDatabase": args.source_database,
        "targetDatabase": args.target_database,
        "mode": "apply" if applied else "dry-run",
        "planDigest": plan_digest(plan),
        "sourceCounts": dict(plan.source_counts),
        "targetProtectedCollectionsNonempty": list(plan.target_protected_nonempty),
        "summary": {
            action: sum(change.action == action for change in plan.changes)
            for action in ("create", "update", "conflict", "unchanged")
        },
        "documents": [
            {
                "path": f"{change.collection}/{change.document_id}",
                "action": change.action,
                "changedFields": list(change.changed_fields),
            }
            for change in plan.changes
        ],
        "verificationMismatches": list(verification_mismatches),
    }


def print_summary(payload: Mapping[str, Any]) -> None:
    print(
        f"Mode: {payload['mode']} | {payload['sourceDatabase']} -> "
        f"{payload['targetDatabase']}"
    )
    print(f"Plan digest: {payload['planDigest']}")
    print("Source counts: " + json.dumps(payload["sourceCounts"], sort_keys=True))
    print("Summary: " + json.dumps(payload["summary"], sort_keys=True))
    protected = payload["targetProtectedCollectionsNonempty"]
    if protected:
        print("Production transactional data detected: " + ", ".join(protected))
    for document in payload["documents"]:
        fields = ",".join(document["changedFields"])
        suffix = f" [{fields}]" if fields else ""
        print(f"{document['action'].upper():9} {document['path']}{suffix}")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    collections = selected_collections(args)
    source = firestore.Client(project=args.project, database=args.source_database)
    target = firestore.Client(project=args.project, database=args.target_database)
    plan = build_plan(
        source,
        target,
        collections,
        allow_updates=args.allow_updates,
        closure_from=args.closure_from,
    )

    digest = plan_digest(plan)
    if args.apply and args.confirm_plan != digest:
        print(
            f"Refusing apply: reviewed plan digest does not match current plan ({digest}).",
            file=sys.stderr,
        )
        return 5
    if args.apply and plan.conflicts:
        print("Refusing apply: target conflicts require --allow-updates.", file=sys.stderr)
        return 2
    if args.apply and plan.target_protected_nonempty and not args.allow_nonempty_production_data:
        print(
            "Refusing apply: Production transactional data exists; use "
            "--allow-nonempty-production-data only for an approved later config promotion.",
            file=sys.stderr,
        )
        return 3

    verification_mismatches: tuple[str, ...] = ()
    if args.apply:
        apply_plan(target, plan)
        verification_mismatches = verify_plan(target, plan)

    payload = report_payload(
        args,
        plan,
        applied=args.apply,
        verification_mismatches=verification_mismatches,
    )
    print_summary(payload)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    if verification_mismatches:
        print("Post-write verification failed.", file=sys.stderr)
        return 4
    return 0 if not plan.conflicts else 1


if __name__ == "__main__":
    raise SystemExit(main())
