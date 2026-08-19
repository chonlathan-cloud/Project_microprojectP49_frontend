from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import pytest

from scripts.promote_firestore_config import (
    CORE_COLLECTIONS,
    DocumentChange,
    PromotionPlan,
    apply_plan,
    build_plan,
    parse_args,
    plan_digest,
)


@dataclass
class FakeSnapshot:
    id: str
    data: dict[str, Any] | None

    @property
    def exists(self) -> bool:
        return self.data is not None

    def to_dict(self) -> dict[str, Any] | None:
        return self.data


class FakeDocument:
    def __init__(self, collection: FakeCollection, document_id: str):
        self.collection = collection
        self.id = document_id

    def get(self) -> FakeSnapshot:
        return FakeSnapshot(self.id, self.collection.documents.get(self.id))


class FakeQuery:
    def __init__(self, collection: FakeCollection, limit: int):
        self.collection = collection
        self.query_limit = limit

    def stream(self):
        return self.collection.stream()[: self.query_limit]


class FakeCollection:
    def __init__(self, documents: dict[str, dict[str, Any]]):
        self.documents = documents

    def stream(self) -> list[FakeSnapshot]:
        return [FakeSnapshot(key, value) for key, value in self.documents.items()]

    def limit(self, count: int) -> FakeQuery:
        return FakeQuery(self, count)

    def document(self, document_id: str) -> FakeDocument:
        return FakeDocument(self, document_id)


class FakeBatch:
    def __init__(self):
        self.writes: list[tuple[FakeDocument, dict[str, Any]]] = []

    def set(self, document: FakeDocument, data: dict[str, Any]) -> None:
        self.writes.append((document, data))

    def commit(self) -> None:
        for document, data in self.writes:
            document.collection.documents[document.id] = data


class FakeClient:
    def __init__(self, collections: dict[str, dict[str, dict[str, Any]]]):
        self.collections = collections

    def collection(self, name: str) -> FakeCollection:
        return FakeCollection(self.collections.setdefault(name, {}))

    def batch(self) -> FakeBatch:
        return FakeBatch()


def core_source() -> FakeClient:
    return FakeClient(
        {
            "branches": {"branch_001": {"active": True}},
            "services": {"service-1": {"priceSatang": 60_000}},
            "resources": {"bed_001": {"active": True}},
        }
    )


def test_dry_run_plans_creates_without_copying_transactional_data() -> None:
    source = core_source()
    source.collections["bookings"] = {"booking-1": {"status": "PENDING"}}
    plan = build_plan(source, FakeClient({}), CORE_COLLECTIONS, allow_updates=False)

    assert {change.collection for change in plan.writes} == set(CORE_COLLECTIONS)
    assert all(change.action == "create" for change in plan.changes)


def test_existing_difference_is_conflict_unless_updates_are_allowed() -> None:
    target = FakeClient({"services": {"service-1": {"priceSatang": 50_000}}})
    conflict = build_plan(core_source(), target, CORE_COLLECTIONS, allow_updates=False)
    update = build_plan(core_source(), target, CORE_COLLECTIONS, allow_updates=True)

    assert [item.action for item in conflict.changes if item.collection == "services"] == [
        "conflict"
    ]
    assert [item.action for item in update.changes if item.collection == "services"] == [
        "update"
    ]


def test_special_closures_are_filtered_by_explicit_cutoff() -> None:
    source = core_source()
    source.collections["special_closures"] = {
        "past": {"localDate": "2026-08-01"},
        "future": {"localDate": "2026-09-01"},
    }
    plan = build_plan(
        source,
        FakeClient({}),
        (*CORE_COLLECTIONS, "special_closures"),
        allow_updates=False,
        closure_from=date(2026, 8, 18),
    )

    closure_paths = [
        change.document_id for change in plan.changes if change.collection == "special_closures"
    ]
    assert closure_paths == ["future"]


def test_target_transactional_data_is_reported() -> None:
    target = FakeClient({"bookings": {"booking-1": {"status": "CONFIRMED"}}})
    plan = build_plan(core_source(), target, CORE_COLLECTIONS, allow_updates=False)
    assert plan.target_protected_nonempty == ("bookings",)


def test_apply_rejects_unresolved_conflicts() -> None:
    plan = PromotionPlan(
        (
            DocumentChange(
                collection="services",
                document_id="service-1",
                action="conflict",
                source_data={"active": True},
            ),
        ),
        {"services": 1},
        (),
    )
    with pytest.raises(RuntimeError, match="unresolved target conflicts"):
        apply_plan(FakeClient({}), plan)


def test_apply_requires_exact_target_confirmation() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--apply", "--confirm-target", "wrong-db", "--confirm-plan", "digest"])


def test_apply_requires_reviewed_plan_digest() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--apply", "--confirm-target", "spa-db"])


def test_plan_digest_changes_when_source_values_change() -> None:
    first = build_plan(core_source(), FakeClient({}), CORE_COLLECTIONS, allow_updates=False)
    changed_source = core_source()
    changed_source.collections["services"]["service-1"]["priceSatang"] = 65_000
    second = build_plan(changed_source, FakeClient({}), CORE_COLLECTIONS, allow_updates=False)
    assert plan_digest(first) != plan_digest(second)


def test_plan_digest_changes_when_target_values_change() -> None:
    first_target = FakeClient({"services": {"service-1": {"priceSatang": 50_000}}})
    second_target = FakeClient({"services": {"service-1": {"priceSatang": 55_000}}})
    first = build_plan(core_source(), first_target, CORE_COLLECTIONS, allow_updates=True)
    second = build_plan(core_source(), second_target, CORE_COLLECTIONS, allow_updates=True)
    assert plan_digest(first) != plan_digest(second)


def test_apply_writes_allowlisted_plan_atomically() -> None:
    target = FakeClient({})
    plan = build_plan(core_source(), target, CORE_COLLECTIONS, allow_updates=False)
    apply_plan(target, plan)
    assert target.collections["services"]["service-1"] == {"priceSatang": 60_000}
