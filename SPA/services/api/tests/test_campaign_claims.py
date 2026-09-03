from datetime import UTC, datetime

import pytest

from app.core.errors import LineFriendshipRequired, ValidationDomainError
from app.domains.campaigns import service
from app.integrations.line_identity import line_identity_hash


class Snapshot:
    def __init__(self, document_id: str, data: dict[str, object] | None) -> None:
        self.id = document_id
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class Document:
    def __init__(self, database: "Database", collection: str, document_id: str) -> None:
        self.database = database
        self.collection = collection
        self.id = document_id

    def get(self, transaction=None):
        return Snapshot(self.id, self.database.data.get(self.collection, {}).get(self.id))


class Collection:
    def __init__(self, database: "Database", name: str) -> None:
        self.database = database
        self.name = name

    def document(self, document_id: str | None = None):
        if document_id is None:
            self.database.counter += 1
            document_id = f"generated-{self.database.counter:03d}"
        return Document(self.database, self.name, document_id)


class Transaction:
    def __init__(self, database: "Database") -> None:
        self.database = database

    def set(self, ref: Document, value: dict[str, object], merge: bool = False) -> None:
        collection = self.database.data.setdefault(ref.collection, {})
        if merge and ref.id in collection:
            collection[ref.id] = {**collection[ref.id], **value}
        else:
            collection[ref.id] = dict(value)


class Database:
    def __init__(self) -> None:
        self.counter = 0
        self.data: dict[str, dict[str, dict[str, object]]] = {
            "campaigns": {
                "welcome-50": {
                    "status": "ACTIVE",
                    "nameTh": "รับส่วนลด 50 บาท",
                    "nameEn": "Get THB 50 off",
                    "benefit": {
                        "type": "FIXED_DISCOUNT",
                        "amountSatang": 5000,
                        "currency": "THB",
                    },
                    "privacyNoticeVersion": "privacy-test-v1",
                }
            }
        }

    def collection(self, name: str):
        return Collection(self, name)

    def transaction(self):
        return Transaction(self)


@pytest.fixture
def database(monkeypatch) -> Database:
    value = Database()
    monkeypatch.setattr(service.firestore, "transactional", lambda function: function)
    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "line_customer_login_channel_id": "line-login-test",
                "privacy_notice_version": "privacy-test-v1",
            },
        )(),
    )
    return value


def claim(
    database: Database,
    *,
    idempotency_key: str,
    marketing: bool = False,
    friendship_confirmed: bool = False,
):
    return service.claim_campaign(
        database,
        campaign_code="welcome-50",
        full_name="มณี สุขใจ",
        phone="081-234-5678",
        birth_day=29,
        birth_month=2,
        birth_year=1992,
        gender=None,
        privacy_acknowledged=True,
        birthday_marketing_consent=marketing,
        line_friendship_confirmed=friendship_confirmed,
        idempotency_key=idempotency_key,
        line_identity={"sub": "line-user-001"},
        now=datetime(2026, 8, 20, 10, tzinfo=UTC),
    )


def test_claim_creates_separated_customer_coupon_and_consent_records(database) -> None:
    result = claim(database, idempotency_key="claim-request-001", marketing=True)

    assert result["alreadyClaimed"] is False
    assert result["coupon"]["amountSatang"] == 5000
    assert result["coupon"]["expiresAt"] is None
    assert len(database.data["customers"]) == 1
    private = next(iter(database.data["customer_private"].values()))
    assert private["phoneE164"] == "+66812345678"
    assert private["birthMonthDay"] == "02-29"
    assert private["birthYear"] == 1992
    marketing_profile = next(iter(database.data["marketing_profiles"].values()))
    assert marketing_profile["birthYear"] == 1992
    summary = next(iter(database.data["customers"].values()))
    assert "phoneE164" not in summary
    assert summary["phoneMasked"] == "081-xxx-5678"
    receipts = list(database.data["consent_receipts"].values())
    assert {item["purposeId"] for item in receipts} == {
        "COUPON_FULFILLMENT",
        "BIRTHDAY_MARKETING",
    }
    assert any(item["action"] == "GRANTED" for item in receipts)
    assert "raw-line-id-token" not in str(database.data)


def test_second_claim_for_same_line_identity_returns_existing_coupon(database) -> None:
    first = claim(database, idempotency_key="claim-request-001")
    second = claim(database, idempotency_key="claim-request-002")

    assert second["alreadyClaimed"] is True
    assert second["coupon"]["code"] == first["coupon"]["code"]
    assert len(database.data["coupons"]) == 1


def test_existing_coupon_submission_refreshes_birth_year_and_consent(database) -> None:
    claim(database, idempotency_key="claim-request-original")
    customer_id = next(iter(database.data["customer_private"]))
    database.data["customer_private"][customer_id].pop("birthYear")
    database.data["marketing_profiles"][customer_id].pop("birthYear")

    result = claim(
        database,
        idempotency_key="claim-request-profile-refresh",
        marketing=True,
    )

    assert result["alreadyClaimed"] is True
    assert len(database.data["coupons"]) == 1
    assert database.data["customer_private"][customer_id]["birthYear"] == 1992
    assert database.data["marketing_profiles"][customer_id]["birthYear"] == 1992
    assert database.data["marketing_profiles"][customer_id][
        "birthdayMarketingStatus"
    ] == "GRANTED"
    assert any(
        event["eventType"] == "CAMPAIGN_CUSTOMER_PROFILE_UPDATED"
        for event in database.data["audit_events"].values()
    )


def test_invalid_calendar_day_is_rejected_before_writes(database) -> None:
    with pytest.raises(ValidationDomainError, match="Birth day is invalid"):
        service.claim_campaign(
            database,
            campaign_code="welcome-50",
            full_name="Manee Sukjai",
            phone="0812345678",
            birth_day=31,
            birth_month=4,
            birth_year=1992,
            gender=None,
            privacy_acknowledged=True,
            birthday_marketing_consent=False,
            idempotency_key="claim-request-003",
            line_identity={"sub": "line-user-002"},
        )

    assert "coupons" not in database.data


def test_future_birth_year_is_rejected_before_writes(database) -> None:
    with pytest.raises(ValidationDomainError, match="Birth year is invalid"):
        service.claim_campaign(
            database,
            campaign_code="welcome-50",
            full_name="Manee Sukjai",
            phone="0812345678",
            birth_day=1,
            birth_month=9,
            birth_year=2027,
            gender=None,
            privacy_acknowledged=True,
            birthday_marketing_consent=False,
            idempotency_key="claim-request-future-year",
            line_identity={"sub": "line-user-future-year"},
            now=datetime(2026, 9, 3, tzinfo=UTC),
        )

    assert "coupons" not in database.data


def test_non_leap_year_february_29_is_rejected_before_writes(database) -> None:
    with pytest.raises(ValidationDomainError, match="Birth day is invalid"):
        service.claim_campaign(
            database,
            campaign_code="welcome-50",
            full_name="Manee Sukjai",
            phone="0812345678",
            birth_day=29,
            birth_month=2,
            birth_year=1991,
            gender=None,
            privacy_acknowledged=True,
            birthday_marketing_consent=False,
            idempotency_key="claim-request-non-leap-year",
            line_identity={"sub": "line-user-non-leap-year"},
        )

    assert "coupons" not in database.data


def test_marketing_consent_is_optional_and_denial_is_recorded(database) -> None:
    claim(database, idempotency_key="claim-request-004", marketing=False)

    marketing_receipt = next(
        item
        for item in database.data["consent_receipts"].values()
        if item["purposeId"] == "BIRTHDAY_MARKETING"
    )
    assert marketing_receipt["action"] == "DENIED"


def test_campaign_can_require_active_line_friendship(database) -> None:
    database.data["campaigns"]["welcome-50"]["eligibility"] = {
        "maxClaimsPerCustomer": 1,
        "requiresFollowing": True,
    }
    with pytest.raises(LineFriendshipRequired, match="friendship is required"):
        claim(database, idempotency_key="claim-request-005")

    identity_id = line_identity_hash("line-user-001", "line-login-test")
    database.data.setdefault("customer_identity_links", {})[identity_id] = {
        "customerId": "customer-from-follow",
        "friendStatus": "FOLLOWING",
    }
    result = claim(database, idempotency_key="claim-request-006")
    assert result["coupon"]["status"] == "ISSUED"


def test_server_verified_friendship_allows_existing_follower_without_crm_record(
    database,
) -> None:
    database.data["campaigns"]["welcome-50"]["eligibility"] = {
        "maxClaimsPerCustomer": 1,
        "requiresFollowing": True,
    }
    friendship_id = line_identity_hash("line-user-001", "line-login-test")
    database.data.setdefault("line_friendships", {})[friendship_id] = {
        "status": "FOLLOWING",
        "evidenceSource": "FOLLOWER_SYNC",
        "assurance": "SERVER_VERIFIED",
    }

    result = claim(database, idempotency_key="claim-request-007")

    assert result["coupon"]["status"] == "ISSUED"
    participation = next(iter(database.data["campaign_participations"].values()))
    assert participation["friendshipEvidence"] == "FOLLOWER_SYNC"


def test_campaign_can_accept_liff_friendship_evidence_for_existing_follower(
    database,
) -> None:
    database.data["campaigns"]["welcome-50"]["eligibility"] = {
        "maxClaimsPerCustomer": 1,
        "requiresFollowing": True,
        "allowLiffFriendshipEvidence": True,
    }

    result = claim(
        database,
        idempotency_key="claim-request-008",
        friendship_confirmed=True,
    )

    assert result["coupon"]["status"] == "ISSUED"
    friendship = next(iter(database.data["line_friendships"].values()))
    assert friendship["status"] == "REPORTED_FOLLOWING"
    assert friendship["evidenceSource"] == "LIFF_CLIENT"
    assert friendship["assurance"] == "CLIENT_ATTESTED"
    identity = next(iter(database.data["customer_identity_links"].values()))
    assert identity["friendStatus"] == "REPORTED_FOLLOWING"
    summary = next(iter(database.data["customers"].values()))
    assert summary["friendStatus"] == "REPORTED_FOLLOWING"


def test_liff_evidence_is_rejected_unless_campaign_explicitly_allows_it(
    database,
) -> None:
    database.data["campaigns"]["welcome-50"]["eligibility"] = {
        "maxClaimsPerCustomer": 1,
        "requiresFollowing": True,
        "allowLiffFriendshipEvidence": False,
    }

    with pytest.raises(LineFriendshipRequired):
        claim(
            database,
            idempotency_key="claim-request-009",
            friendship_confirmed=True,
        )

    assert "coupons" not in database.data


def test_liff_flag_is_not_recorded_when_campaign_does_not_require_friendship(
    database,
) -> None:
    result = claim(
        database,
        idempotency_key="claim-request-010",
        friendship_confirmed=True,
    )

    assert result["coupon"]["status"] == "ISSUED"
    assert "line_friendships" not in database.data
    identity = next(iter(database.data["customer_identity_links"].values()))
    assert identity["friendStatus"] == "UNKNOWN"
