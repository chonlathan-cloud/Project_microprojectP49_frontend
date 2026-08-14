from app.domains.availability.allocator import Requirement, Resource, deterministic_allocate


def test_allocator_uses_stable_best_fit_and_respects_capacity() -> None:
    resources = [
        Resource("bed-b", "BED", 2, frozenset({"massage"}), 10),
        Resource("bed-a", "BED", 1, frozenset({"massage"}), 10),
    ]
    requirements = [Requirement(0, "BED", 1, ("1400",), compatible_tags=frozenset({"massage"}))]
    allocation = deterministic_allocate(requirements, resources, set(), {})
    assert allocation is not None
    assert allocation[0].resource_id == "bed-a"


def test_two_participants_are_all_or_nothing() -> None:
    resources = [Resource("bed-a", "BED", 1, frozenset({"massage"}), 10)]
    requirements = [
        Requirement(0, "BED", 1, ("1400",)),
        Requirement(1, "BED", 1, ("1400",)),
    ]
    assert deterministic_allocate(requirements, resources, set(), {}) is None


def test_blocked_resource_is_not_allocated() -> None:
    resources = [Resource("bed-a", "BED", 1, frozenset(), 10)]
    requirements = [Requirement(0, "BED", 1, ("1400", "1415"))]
    assert deterministic_allocate(requirements, resources, {("bed-a", "1415")}, {}) is None
