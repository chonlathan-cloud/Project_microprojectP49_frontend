import pytest
from fastapi.testclient import TestClient
from google.cloud import firestore

from app.core.auth import require_admin_user
from app.infrastructure.firestore import get_firestore_client
from app.main import app

client = TestClient(app)


def test_admin_phase_one_modules_require_authentication() -> None:
    for path in (
        "/api/v1/admin/resources",
        "/api/v1/admin/closures",
        "/api/v1/admin/services",
        "/api/v1/admin/therapists",
        "/api/v1/admin/notifications",
        "/api/v1/admin/line-group-candidates",
    ):
        response = client.get(path)
        assert response.status_code == 401
        assert response.json()["detail"] == "Bearer token required"


class FakeSnapshot:
    exists = True

    def to_dict(self) -> dict[str, object]:
        return {"state": "ENQUEUED", "enqueueGeneration": 0}


class FakeDocument:
    def __init__(self) -> None:
        self.update: dict[str, object] = {}

    def get(self) -> FakeSnapshot:
        return FakeSnapshot()

    def set(self, value: dict[str, object], merge: bool = False) -> None:
        assert merge is True
        self.update = value


class FakeCollection:
    def __init__(self, notification: FakeDocument) -> None:
        self.notification = notification

    def document(self, document_id: str | None = None):
        if document_id == "event-001":
            return self.notification
        return type("AuditDocument", (), {"set": lambda self, value: None})()


class FakeFirestore:
    def __init__(self) -> None:
        self.notification = FakeDocument()

    def collection(self, name: str) -> FakeCollection:
        assert name in {"notification_outbox", "audit_events"}
        return FakeCollection(self.notification)


def test_notification_retry_advances_enqueue_generation() -> None:
    database = FakeFirestore()
    previous_auth = app.dependency_overrides.get(require_admin_user)
    previous_firestore = app.dependency_overrides.get(get_firestore_client)
    app.dependency_overrides[require_admin_user] = lambda: {"uid": "admin-001"}
    app.dependency_overrides[get_firestore_client] = lambda: database
    try:
        response = client.post("/api/v1/admin/notifications/event-001:retry")
    finally:
        if previous_auth is None:
            app.dependency_overrides.pop(require_admin_user, None)
        else:
            app.dependency_overrides[require_admin_user] = previous_auth
        if previous_firestore is None:
            app.dependency_overrides.pop(get_firestore_client, None)
        else:
            app.dependency_overrides[get_firestore_client] = previous_firestore

    assert response.status_code == 200
    assert response.json() == {"eventId": "event-001", "state": "RETRYABLE"}
    assert database.notification.update["state"] == "RETRYABLE"
    increment = database.notification.update["enqueueGeneration"]
    assert isinstance(increment, firestore.Increment)
    assert increment.value == 1


class ServiceSnapshot:
    def __init__(self, data: dict[str, object] | None = None) -> None:
        self.data = data
        self.exists = data is not None

    def to_dict(self) -> dict[str, object]:
        return dict(self.data or {})


class ServiceDocument:
    def __init__(self, database: "ServiceFirestore", document_id: str) -> None:
        self.database = database
        self.document_id = document_id

    def get(self) -> ServiceSnapshot:
        return ServiceSnapshot(self.database.services.get(self.document_id))

    def create(self, value: dict[str, object]) -> None:
        assert self.document_id not in self.database.services
        self.database.services[self.document_id] = value

    def update(self, value: dict[str, object]) -> None:
        self.database.services[self.document_id].update(value)

    def set(self, value: dict[str, object]) -> None:
        self.database.audits.append(value)


class ServiceCollection:
    def __init__(self, database: "ServiceFirestore", name: str) -> None:
        self.database = database
        self.name = name

    def stream(self) -> list[ServiceSnapshot]:
        return [ServiceSnapshot(item) for item in self.database.services.values()]

    def document(self, document_id: str | None = None) -> ServiceDocument:
        return ServiceDocument(self.database, document_id or f"audit-{len(self.database.audits)}")


class ServiceFirestore:
    def __init__(self) -> None:
        self.services: dict[str, dict[str, object]] = {
            "existing": {"serviceId": "existing", "branchId": "branch_001", "displayOrder": 20}
        }
        self.audits: list[dict[str, object]] = []

    def collection(self, name: str) -> ServiceCollection:
        assert name in {"services", "audit_events"}
        return ServiceCollection(self, name)


def _with_service_dependencies(database: ServiceFirestore) -> tuple[object, object]:
    previous_auth = app.dependency_overrides.get(require_admin_user)
    previous_firestore = app.dependency_overrides.get(get_firestore_client)
    app.dependency_overrides[require_admin_user] = lambda: {"uid": "staff-001", "role": "STAFF"}
    app.dependency_overrides[get_firestore_client] = lambda: database
    return previous_auth, previous_firestore


def _restore_dependencies(previous_auth: object, previous_firestore: object) -> None:
    if previous_auth is None:
        app.dependency_overrides.pop(require_admin_user, None)
    else:
        app.dependency_overrides[require_admin_user] = previous_auth
    if previous_firestore is None:
        app.dependency_overrides.pop(get_firestore_client, None)
    else:
        app.dependency_overrides[get_firestore_client] = previous_firestore


def test_staff_can_create_service_with_initial_variant() -> None:
    database = ServiceFirestore()
    previous_auth, previous_firestore = _with_service_dependencies(database)
    try:
        response = client.post(
            "/api/v1/admin/services",
            json={
                "category": "MASSAGE",
                "nameTh": "บริการใหม่",
                "nameEn": "New Service",
                "durationMinutes": 60,
                "priceSatang": 50000,
                "pricingMode": "PER_PARTICIPANT",
                "requiredPax": 1,
            },
        )
    finally:
        _restore_dependencies(previous_auth, previous_firestore)

    assert response.status_code == 201
    created = database.services[response.json()["serviceId"]]
    assert created["displayOrder"] == 30
    assert created["category"] == "MASSAGE"
    assert created["active"] is True
    assert created["variants"][0]["priceSatang"] == 50000
    assert database.audits[-1]["eventType"] == "SERVICE_CREATED"


def test_staff_can_create_service_with_multiple_duration_variants() -> None:
    database = ServiceFirestore()
    previous_auth, previous_firestore = _with_service_dependencies(database)
    try:
        response = client.post(
            "/api/v1/admin/services",
            json={
                "category": "MASSAGE",
                "nameTh": "นวดคอ บ่า ไหล่",
                "nameEn": "Neck and Shoulder Massage",
                "variants": [
                    {"durationMinutes": 60, "priceSatang": 50000},
                    {"durationMinutes": 30, "priceSatang": 30000},
                ],
                "pricingMode": "PER_PARTICIPANT",
                "requiredPax": 1,
            },
        )
    finally:
        _restore_dependencies(previous_auth, previous_firestore)

    assert response.status_code == 201
    payload = response.json()
    created = database.services[payload["serviceId"]]
    assert [variant["durationMinutes"] for variant in created["variants"]] == [30, 60]
    assert [variant["priceSatang"] for variant in created["variants"]] == [30000, 50000]
    assert payload["variantIds"] == [
        f"{payload['serviceId']}-30",
        f"{payload['serviceId']}-60",
    ]


def test_service_create_rejects_duplicate_durations() -> None:
    database = ServiceFirestore()
    previous_auth, previous_firestore = _with_service_dependencies(database)
    try:
        response = client.post(
            "/api/v1/admin/services",
            json={
                "category": "MASSAGE",
                "nameTh": "บริการใหม่",
                "nameEn": "New Service",
                "variants": [
                    {"durationMinutes": 60, "priceSatang": 50000},
                    {"durationMinutes": 60, "priceSatang": 60000},
                ],
            },
        )
    finally:
        _restore_dependencies(previous_auth, previous_firestore)

    assert response.status_code == 422
    assert response.json()["detail"] == "Service durations must be unique"


def test_staff_can_add_duration_variant_to_existing_service() -> None:
    database = ServiceFirestore()
    database.services["existing"].update(
        {
            "version": 1,
            "variants": [
                {
                    "variantId": "existing-30",
                    "durationMinutes": 30,
                    "priceSatang": 30000,
                    "pricingMode": "PER_PARTICIPANT",
                    "requiredPax": 1,
                    "active": True,
                    "resourceRequirements": [{"resourceId": "bed", "quantity": 1}],
                }
            ],
        }
    )
    previous_auth, previous_firestore = _with_service_dependencies(database)
    try:
        response = client.post(
            "/api/v1/admin/services/existing/variants",
            json={"durationMinutes": 60, "priceSatang": 50000, "expectedVersion": 1},
        )
    finally:
        _restore_dependencies(previous_auth, previous_firestore)

    assert response.status_code == 201
    assert response.json()["variantId"] == "existing-60"
    assert database.services["existing"]["version"] == 2
    variants = database.services["existing"]["variants"]
    assert [variant["durationMinutes"] for variant in variants] == [30, 60]
    assert variants[1]["resourceRequirements"] == [{"resourceId": "bed", "quantity": 1}]
    assert database.audits[-1]["eventType"] == "SERVICE_VARIANT_CREATED"


def test_service_variant_create_rejects_duplicate_duration() -> None:
    database = ServiceFirestore()
    database.services["existing"].update(
        {
            "version": 1,
            "variants": [
                {
                    "variantId": "existing-60",
                    "durationMinutes": 60,
                    "priceSatang": 50000,
                    "pricingMode": "PER_PARTICIPANT",
                    "requiredPax": 1,
                    "active": True,
                    "resourceRequirements": [],
                }
            ],
        }
    )
    previous_auth, previous_firestore = _with_service_dependencies(database)
    try:
        response = client.post(
            "/api/v1/admin/services/existing/variants",
            json={"durationMinutes": 60, "priceSatang": 60000, "expectedVersion": 1},
        )
    finally:
        _restore_dependencies(previous_auth, previous_firestore)

    assert response.status_code == 409
    assert response.json()["detail"] == "A service variant with this duration already exists"
    assert len(database.services["existing"]["variants"]) == 1


def test_staff_can_change_service_category() -> None:
    database = ServiceFirestore()
    database.services["existing"].update({"version": 1, "category": "MASSAGE"})
    previous_auth, previous_firestore = _with_service_dependencies(database)
    try:
        response = client.patch(
            "/api/v1/admin/services/existing",
            json={"category": "SIGNATURE", "expectedVersion": 1},
        )
    finally:
        _restore_dependencies(previous_auth, previous_firestore)

    assert response.status_code == 200
    assert database.services["existing"]["category"] == "SIGNATURE"
    assert database.services["existing"]["version"] == 2
    assert database.audits[-1]["eventType"] == "SERVICE_UPDATED"


class TherapistDocument:
    def __init__(self, database: "TherapistFirestore", document_id: str) -> None:
        self.database = database
        self.document_id = document_id

    def set(self, value: dict[str, object]) -> None:
        if self.document_id.startswith("therapist_"):
            self.database.therapists[self.document_id] = value
        else:
            self.database.audits.append(value)


class TherapistCollection:
    def __init__(self, database: "TherapistFirestore") -> None:
        self.database = database

    def document(self, document_id: str | None = None) -> TherapistDocument:
        return TherapistDocument(
            self.database,
            document_id or f"audit-{len(self.database.audits)}",
        )


class TherapistFirestore:
    def __init__(self) -> None:
        self.therapists: dict[str, dict[str, object]] = {}
        self.audits: list[dict[str, object]] = []

    def collection(self, name: str) -> TherapistCollection:
        assert name in {"therapists", "audit_events"}
        return TherapistCollection(self)


@pytest.mark.parametrize("role", ["ADMIN", "STAFF"])
def test_admin_and_staff_can_register_therapists(role: str) -> None:
    database = TherapistFirestore()
    previous_auth = app.dependency_overrides.get(require_admin_user)
    previous_firestore = app.dependency_overrides.get(get_firestore_client)
    app.dependency_overrides[require_admin_user] = lambda: {
        "uid": f"{role.lower()}-001",
        "role": role,
    }
    app.dependency_overrides[get_firestore_client] = lambda: database
    try:
        response = client.post(
            "/api/v1/admin/therapists",
            json={"branchId": "branch_001", "displayName": "  คุณนิด  "},
        )
    finally:
        _restore_dependencies(previous_auth, previous_firestore)

    assert response.status_code == 201
    therapist = database.therapists[response.json()["therapistId"]]
    assert therapist["displayName"] == "คุณนิด"
    assert therapist["active"] is True
    assert database.audits[-1]["eventType"] == "THERAPIST_CREATED"


class AssignmentBookingReference:
    def __init__(self, database: "AssignmentFirestore") -> None:
        self.database = database

    def get(self, transaction=None):
        return AssignmentSnapshot(self.database.booking, self)

    def update(self, value: dict[str, object]) -> None:
        self.database.booking.update(value)


class AssignmentSnapshot:
    exists = True

    def __init__(
        self,
        data: dict[str, object],
        reference: AssignmentBookingReference | None = None,
    ) -> None:
        self.data = data
        self.reference = reference

    def to_dict(self) -> dict[str, object]:
        return dict(self.data)


class AssignmentDocument:
    def __init__(self, database: "AssignmentFirestore", document_id: str) -> None:
        self.database = database
        self.document_id = document_id

    def get(self, transaction=None) -> AssignmentSnapshot:
        return AssignmentSnapshot(self.database.therapists[self.document_id])

    def set(self, value: dict[str, object]) -> None:
        self.database.audits.append(value)


class AssignmentCollection:
    def __init__(self, database: "AssignmentFirestore", name: str) -> None:
        self.database = database
        self.name = name

    def where(self, *args: object, **kwargs: object) -> "AssignmentCollection":
        return self

    def limit(self, value: int) -> "AssignmentCollection":
        return self

    def stream(self) -> list[AssignmentSnapshot]:
        assert self.name == "bookings"
        return [
            AssignmentSnapshot(
                self.database.booking,
                AssignmentBookingReference(self.database),
            )
        ]

    def document(self, document_id: str | None = None) -> AssignmentDocument:
        return AssignmentDocument(
            self.database,
            document_id or f"audit-{len(self.database.audits)}",
        )


class AssignmentFirestore:
    def __init__(self) -> None:
        self.booking: dict[str, object] = {
            "publicBookingId": "BK-001",
            "branchId": "branch_001",
            "status": "CONFIRMED",
            "pax": 2,
            "version": 4,
        }
        self.therapists: dict[str, dict[str, object]] = {
            "therapist_1": {"displayName": "คุณนิด", "active": True, "branchId": "branch_001"},
            "therapist_2": {"displayName": "คุณอ้อย", "active": True, "branchId": "branch_001"},
        }
        self.audits: list[dict[str, object]] = []

    def transaction(self):
        return type(
            "Transaction",
            (),
            {
                "update": lambda self, ref, data: ref.update(data),
                "set": lambda self, ref, data: ref.set(data),
            },
        )()

    def collection(self, name: str) -> AssignmentCollection:
        assert name in {"bookings", "therapists", "audit_events"}
        return AssignmentCollection(self, name)


def test_staff_assignment_updates_booking_projection(monkeypatch) -> None:
    monkeypatch.setattr(firestore, "transactional", lambda fn: lambda tx: fn(tx))
    database = AssignmentFirestore()
    previous_auth = app.dependency_overrides.get(require_admin_user)
    previous_firestore = app.dependency_overrides.get(get_firestore_client)
    app.dependency_overrides[require_admin_user] = lambda: {
        "uid": "staff-001",
        "role": "STAFF",
    }
    app.dependency_overrides[get_firestore_client] = lambda: database
    try:
        response = client.put(
            "/api/v1/admin/bookings/BK-001/assignments",
            json={
                "therapistIds": ["therapist_1", "therapist_2"],
                "expectedVersion": 4,
            },
        )
    finally:
        _restore_dependencies(previous_auth, previous_firestore)

    assert response.status_code == 200, response.text
    assert database.booking["assignmentState"] == "ASSIGNED"
    assert database.booking["therapistName"] == "คุณนิด, คุณอ้อย"
    assert database.booking["version"] == 5
    assert database.audits[-1]["eventType"] == "THERAPISTS_ASSIGNED"


def test_assignment_rejects_same_therapist_for_two_participants(monkeypatch) -> None:
    monkeypatch.setattr(firestore, "transactional", lambda fn: lambda tx: fn(tx))
    database = AssignmentFirestore()
    previous_auth = app.dependency_overrides.get(require_admin_user)
    previous_firestore = app.dependency_overrides.get(get_firestore_client)
    app.dependency_overrides[require_admin_user] = lambda: {
        "uid": "staff-001",
        "role": "STAFF",
    }
    app.dependency_overrides[get_firestore_client] = lambda: database
    try:
        response = client.put(
            "/api/v1/admin/bookings/BK-001/assignments",
            json={
                "therapistIds": ["therapist_1", "therapist_1"],
                "expectedVersion": 4,
            },
        )
    finally:
        _restore_dependencies(previous_auth, previous_firestore)

    assert response.status_code == 422
    assert "different therapist" in response.json()["detail"]
    assert database.booking["version"] == 4
