from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Resource:
    id: str
    resource_type: str
    capacity_units: int
    tags: frozenset[str]
    allocation_priority: int
    active: bool = True


@dataclass(frozen=True, slots=True)
class Requirement:
    participant_index: int
    resource_type: str
    units: int
    bucket_ids: tuple[str, ...]
    compatible_resource_ids: frozenset[str] = frozenset()
    compatible_tags: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class Allocation:
    participant_index: int
    resource_id: str
    resource_type: str
    units: int
    bucket_ids: tuple[str, ...]


def _is_compatible(requirement: Requirement, resource: Resource) -> bool:
    if not resource.active or resource.resource_type != requirement.resource_type:
        return False
    if (
        requirement.compatible_resource_ids
        and resource.id not in requirement.compatible_resource_ids
    ):
        return False
    return not requirement.compatible_tags or bool(requirement.compatible_tags & resource.tags)


def deterministic_allocate(
    requirements: list[Requirement],
    resources: list[Resource],
    blocked: set[tuple[str, str]],
    bucket_usage: dict[tuple[str, str], int],
) -> list[Allocation] | None:
    """Allocate every requirement or return None without partially committing."""
    candidates_by_requirement: dict[Requirement, list[Resource]] = {}
    for requirement in requirements:
        candidates = [resource for resource in resources if _is_compatible(requirement, resource)]
        candidates_by_requirement[requirement] = candidates

    ordered = sorted(
        requirements,
        key=lambda item: (
            len(candidates_by_requirement[item]),
            item.participant_index,
            item.resource_type,
        ),
    )
    provisional: dict[tuple[str, str], int] = defaultdict(int)

    def search(index: int, assignments: list[Allocation]) -> list[Allocation] | None:
        if index == len(ordered):
            return assignments.copy()

        requirement = ordered[index]
        viable: list[tuple[int, Resource]] = []
        for resource in candidates_by_requirement[requirement]:
            if any((resource.id, bucket_id) in blocked for bucket_id in requirement.bucket_ids):
                continue
            remaining_values = []
            for bucket_id in requirement.bucket_ids:
                used = bucket_usage.get((resource.id, bucket_id), 0)
                used += provisional[(resource.id, bucket_id)]
                remaining_values.append(resource.capacity_units - used - requirement.units)
            if remaining_values and min(remaining_values) >= 0:
                viable.append((min(remaining_values), resource))

        viable.sort(key=lambda item: (item[1].allocation_priority, item[0], item[1].id))
        for _, resource in viable:
            for bucket_id in requirement.bucket_ids:
                provisional[(resource.id, bucket_id)] += requirement.units
            assignments.append(
                Allocation(
                    participant_index=requirement.participant_index,
                    resource_id=resource.id,
                    resource_type=requirement.resource_type,
                    units=requirement.units,
                    bucket_ids=requirement.bucket_ids,
                )
            )
            result = search(index + 1, assignments)
            if result is not None:
                return result
            assignments.pop()
            for bucket_id in requirement.bucket_ids:
                provisional[(resource.id, bucket_id)] -= requirement.units
        return None

    if not requirements:
        return []
    return search(0, [])
