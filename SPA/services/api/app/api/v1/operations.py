from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, status
from google.cloud import firestore
from pydantic import BaseModel, ConfigDict, Field

from app.core.auth import require_admin_user
from app.core.errors import ConflictDomainError, NotFoundDomainError, ValidationDomainError
from app.infrastructure.firestore import get_firestore_client

router = APIRouter(prefix="/api/v1/admin", tags=["admin-operations"])


def _camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.title() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True)


class ClosureInput(ApiModel):
    branch_id: str = "branch_001"
    local_date: str
    reason: str = Field(min_length=1, max_length=300)


class ResourceUpdate(ApiModel):
    active: bool
    expected_version: int = Field(ge=1)


class TherapistInput(ApiModel):
    branch_id: str = "branch_001"
    display_name: str = Field(min_length=1, max_length=100)


class AssignmentInput(ApiModel):
    therapist_ids: list[str] = Field(min_length=1, max_length=2)
    expected_version: int = Field(ge=1)


class ServiceUpdate(ApiModel):
    active: bool | None = None
    name_th: str | None = Field(default=None, min_length=1, max_length=160)
    name_en: str | None = Field(default=None, min_length=1, max_length=160)
    expected_version: int = Field(ge=1)


class VariantUpdate(ApiModel):
    price_satang: int | None = Field(default=None, ge=0)
    active: bool | None = None
    expected_version: int = Field(ge=1)


def _audit(
    client: firestore.Client,
    *,
    actor: dict[str, object],
    event_type: str,
    target_id: str,
) -> None:
    client.collection("audit_events").document().set(
        {
            "eventType": event_type,
            "targetId": target_id,
            "actorType": "ADMIN_USER",
            "actorId": actor["uid"],
            "createdAt": datetime.now(UTC),
        }
    )


@router.get("/closures")
async def list_closures(
    _: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
    branch_id: str = "branch_001",
) -> dict[str, object]:
    snapshots = client.collection("special_closures").where("branchId", "==", branch_id).stream()
    items = [{"closureId": item.id, **(item.to_dict() or {})} for item in snapshots]
    items.sort(key=lambda item: str(item.get("localDate", "")))
    return {"items": items}


@router.post("/closures", status_code=status.HTTP_201_CREATED)
async def create_closure(
    request: ClosureInput,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> dict[str, object]:
    try:
        datetime.fromisoformat(request.local_date)
    except ValueError as error:
        raise ValidationDomainError("Closure date is invalid") from error
    closure_id = f"{request.branch_id}_{request.local_date}"
    ref = client.collection("special_closures").document(closure_id)
    ref.set(
        {
            "branchId": request.branch_id,
            "localDate": request.local_date,
            "reason": request.reason,
            "version": 1,
            "createdAt": datetime.now(UTC),
            "createdBy": actor["uid"],
        },
        merge=False,
    )
    _audit(client, actor=actor, event_type="SPECIAL_CLOSURE_CREATED", target_id=closure_id)
    return {"closureId": closure_id, "version": 1}


@router.delete("/closures/{closure_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_closure(
    closure_id: str,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> None:
    ref = client.collection("special_closures").document(closure_id)
    if not ref.get().exists:
        raise NotFoundDomainError("Closure not found")
    ref.delete()
    _audit(client, actor=actor, event_type="SPECIAL_CLOSURE_DELETED", target_id=closure_id)


@router.get("/resources")
async def list_resources(
    _: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
    branch_id: str = "branch_001",
) -> dict[str, object]:
    items = client.collection("resources").where("branchId", "==", branch_id).stream()
    return {"items": [{"resourceId": item.id, **(item.to_dict() or {})} for item in items]}


@router.patch("/resources/{resource_id}")
async def update_resource(
    resource_id: str,
    request: ResourceUpdate,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> dict[str, object]:
    ref = client.collection("resources").document(resource_id)
    snapshot = ref.get()
    if not snapshot.exists:
        raise NotFoundDomainError("Resource not found")
    data = snapshot.to_dict() or {}
    if int(data.get("version", 1)) != request.expected_version:
        raise ConflictDomainError("Resource changed; reload before trying again")
    next_version = request.expected_version + 1
    ref.update({"active": request.active, "version": next_version, "updatedAt": datetime.now(UTC)})
    active_count = len(
        list(
            client.collection("resources")
            .where("branchId", "==", data["branchId"])
            .where("active", "==", True)
            .stream()
        )
    )
    client.collection("branches").document(str(data["branchId"])).set(
        {"activeCapacityUnits": active_count, "updatedAt": datetime.now(UTC)}, merge=True
    )
    _audit(client, actor=actor, event_type="RESOURCE_AVAILABILITY_CHANGED", target_id=resource_id)
    return {"resourceId": resource_id, "active": request.active, "version": next_version}


@router.get("/therapists")
async def list_therapists(
    _: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
    branch_id: str = "branch_001",
) -> dict[str, object]:
    items = client.collection("therapists").where("branchId", "==", branch_id).stream()
    return {"items": [{"therapistId": item.id, **(item.to_dict() or {})} for item in items]}


@router.post("/therapists", status_code=status.HTTP_201_CREATED)
async def create_therapist(
    request: TherapistInput,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> dict[str, object]:
    therapist_id = f"therapist_{uuid4().hex[:12]}"
    client.collection("therapists").document(therapist_id).set(
        {
            "therapistId": therapist_id,
            "branchId": request.branch_id,
            "displayName": request.display_name,
            "active": True,
            "version": 1,
            "createdAt": datetime.now(UTC),
        }
    )
    _audit(client, actor=actor, event_type="THERAPIST_CREATED", target_id=therapist_id)
    return {"therapistId": therapist_id, "version": 1}


@router.post("/bookings/{booking_id}:assign")
async def assign_therapists(
    booking_id: str,
    request: AssignmentInput,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> dict[str, object]:
    matches = list(
        client.collection("bookings").where("publicBookingId", "==", booking_id).limit(1).stream()
    )
    if not matches:
        raise NotFoundDomainError("Booking not found")
    ref = matches[0].reference
    data = matches[0].to_dict() or {}
    if int(data.get("version", 1)) != request.expected_version:
        raise ConflictDomainError("Booking changed; reload before trying again")
    if len(request.therapist_ids) != int(data.get("pax", 1)):
        raise ValidationDomainError("Every participant requires one therapist assignment")
    therapists = [
        client.collection("therapists").document(item).get() for item in request.therapist_ids
    ]
    if any(not item.exists or not (item.to_dict() or {}).get("active") for item in therapists):
        raise ValidationDomainError("Every assigned therapist must be active")
    next_version = request.expected_version + 1
    names = [(item.to_dict() or {}).get("displayName") for item in therapists]
    ref.update(
        {
            "therapistIds": request.therapist_ids,
            "therapistName": ", ".join(str(name) for name in names),
            "assignmentState": "ASSIGNED",
            "version": next_version,
            "updatedAt": datetime.now(UTC),
        }
    )
    _audit(client, actor=actor, event_type="THERAPISTS_ASSIGNED", target_id=booking_id)
    return {"bookingId": booking_id, "assignmentState": "ASSIGNED", "version": next_version}


@router.get("/services")
async def list_admin_services(
    _: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
    branch_id: str = "branch_001",
) -> dict[str, object]:
    snapshots = client.collection("services").where("branchId", "==", branch_id).stream()
    items = [{"serviceId": item.id, **(item.to_dict() or {})} for item in snapshots]
    items.sort(key=lambda item: int(item.get("displayOrder", 0)))
    return {"items": items}


@router.patch("/services/{service_id}")
async def update_service(
    service_id: str,
    request: ServiceUpdate,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> dict[str, object]:
    ref = client.collection("services").document(service_id)
    snapshot = ref.get()
    if not snapshot.exists:
        raise NotFoundDomainError("Service not found")
    data = snapshot.to_dict() or {}
    version = int(data.get("version", 1))
    if version != request.expected_version:
        raise ConflictDomainError("Service changed; reload before trying again")
    changes = request.model_dump(exclude={"expected_version"}, exclude_none=True, by_alias=True)
    if not changes:
        raise ValidationDomainError("At least one service field must change")
    next_version = version + 1
    ref.update({**changes, "version": next_version, "updatedAt": datetime.now(UTC)})
    _audit(client, actor=actor, event_type="SERVICE_UPDATED", target_id=service_id)
    return {"serviceId": service_id, "version": next_version, **changes}


@router.patch("/services/{service_id}/variants/{variant_id}")
async def update_service_variant(
    service_id: str,
    variant_id: str,
    request: VariantUpdate,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> dict[str, object]:
    ref = client.collection("services").document(service_id)
    snapshot = ref.get()
    if not snapshot.exists:
        raise NotFoundDomainError("Service not found")
    data = snapshot.to_dict() or {}
    version = int(data.get("version", 1))
    if version != request.expected_version:
        raise ConflictDomainError("Service changed; reload before trying again")
    changes = request.model_dump(exclude={"expected_version"}, exclude_none=True, by_alias=True)
    if not changes:
        raise ValidationDomainError("At least one variant field must change")
    variants = list(data.get("variants", []))
    found = False
    for variant in variants:
        if variant.get("variantId") == variant_id:
            variant.update(changes)
            found = True
            break
    if not found:
        raise NotFoundDomainError("Service variant not found")
    next_version = version + 1
    ref.update({"variants": variants, "version": next_version, "updatedAt": datetime.now(UTC)})
    _audit(client, actor=actor, event_type="SERVICE_VARIANT_UPDATED", target_id=variant_id)
    return {"serviceId": service_id, "variantId": variant_id, "version": next_version, **changes}


@router.get("/notifications")
async def list_notifications(
    _: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
    limit: int = 100,
) -> dict[str, object]:
    snapshots = list(
        client.collection("notification_outbox").limit(min(max(limit, 1), 200)).stream()
    )
    items = [{"eventId": item.id, **(item.to_dict() or {})} for item in snapshots]
    items.sort(
        key=lambda item: item.get("createdAt") or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    return {"items": items}


@router.get("/line-group-candidates")
async def list_line_group_candidates(
    _: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> dict[str, object]:
    snapshots = list(client.collection("line_group_candidates").stream())
    items = [{"candidateId": item.id, **(item.to_dict() or {})} for item in snapshots]
    items.sort(
        key=lambda item: item.get("lastSeenAt") or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    return {"items": items}


@router.post("/notifications/{event_id}:retry")
async def retry_notification(
    event_id: str,
    actor: Annotated[dict[str, object], Depends(require_admin_user)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> dict[str, object]:
    ref = client.collection("notification_outbox").document(event_id)
    snapshot = ref.get()
    if not snapshot.exists:
        raise NotFoundDomainError("Notification event not found")
    data = snapshot.to_dict() or {}
    if data.get("state") == "SENT":
        raise ConflictDomainError("A sent notification cannot be retried")
    ref.set(
        {
            "state": "RETRYABLE",
            "enqueueGeneration": firestore.Increment(1),
            "updatedAt": datetime.now(UTC),
        },
        merge=True,
    )
    _audit(client, actor=actor, event_type="NOTIFICATION_RETRY_REQUESTED", target_id=event_id)
    return {"eventId": event_id, "state": "RETRYABLE"}
