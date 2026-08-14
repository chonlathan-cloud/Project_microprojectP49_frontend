# SPA 49 — Low-Level Design

| Item | Value |
| --- | --- |
| Product | SPA 49 Booking & Operations |
| Document | Low-Level Design (LLD) |
| Version | 1.1 |
| Status | Implementation baseline |
| Last updated | 14 August 2026 |
| Business baseline | [Business Logic v1.2](./BusinessLogic.md) |
| Architecture baseline | [HLD v1.1](./HLD.md) |
| Technical baseline | [TDD v1.1](./TDD.md) |

## 1. Purpose

This document converts the approved TDD into implementable modules, types, Firestore documents, API payloads, algorithms, infrastructure resources, and verification cases for SPA 49 Phase 1.

Code may refine private helper names, but it must preserve the public contracts, transaction boundaries, security projections, state rules, and traceability defined here. A material change requires updating TDD or recording an Architecture Decision Record before implementation.

## 2. Coding and Contract Conventions

### 2.1 General

- Python uses four-space indentation, type annotations, Pydantic v2, and async FastAPI routes.
- TypeScript/TSX uses two-space indentation and strict compiler settings.
- API JSON fields use `camelCase`; Python internals use `snake_case` aliases.
- Firestore fields use `camelCase` to match API projections where safe.
- UTC timestamps are Firestore timestamp values, not strings inside documents.
- Local date/time search fields remain explicit strings for branch operations.
- Money is integer satang.
- IDs are strings; callers never infer collection paths from public IDs.
- All mutation methods accept a `RequestContext` and write an audit/correlation identifier.

### 2.2 Required Headers

| Header | Use |
| --- | --- |
| `Authorization: Bearer <Firebase ID token>` | Admin API |
| `Idempotency-Key: <UUID v4>` | Public Booking create |
| `X-Request-ID: <UUID>` | Optional caller correlation; validated before use |
| `x-line-signature` | LINE webhook verification |
| `Content-Type: application/json` | JSON endpoints |

LINE ID tokens and Guest status tokens are sent in JSON bodies to prevent accidental URL/access-log exposure.

## 3. Source Tree

```text
SPA/
├── package.json
├── package-lock.json
├── .nvmrc
├── apps/
│   ├── customer-web/
│   │   ├── app/
│   │   │   ├── (booking)/
│   │   │   │   ├── service/page.tsx
│   │   │   │   ├── participants/page.tsx
│   │   │   │   ├── schedule/page.tsx
│   │   │   │   ├── details/page.tsx
│   │   │   │   ├── review/page.tsx
│   │   │   │   └── result/page.tsx
│   │   │   ├── status/page.tsx
│   │   │   ├── layout.tsx
│   │   │   └── page.tsx
│   │   ├── components/
│   │   ├── features/booking/
│   │   ├── features/line-link/
│   │   ├── lib/api.ts
│   │   ├── lib/liff.ts
│   │   └── middleware.ts
│   └── admin-web/
│       ├── app/
│       │   ├── (auth)/login/page.tsx
│       │   └── (dashboard)/
│       │       ├── bookings/
│       │       ├── calendar/
│       │       ├── services/
│       │       ├── capacity/
│       │       ├── therapists/
│       │       ├── users/
│       │       └── settings/
│       ├── components/
│       ├── features/
│       ├── lib/api.ts
│       ├── lib/firebase.ts
│       └── middleware.ts
├── services/
│   ├── api/
│   │   ├── app/
│   │   │   ├── main.py
│   │   │   ├── api/v1/
│   │   │   │   ├── public.py
│   │   │   │   ├── admin_bookings.py
│   │   │   │   ├── admin_catalog.py
│   │   │   │   ├── admin_users.py
│   │   │   │   └── line_webhooks.py
│   │   │   ├── core/
│   │   │   │   ├── config.py
│   │   │   │   ├── errors.py
│   │   │   │   ├── logging.py
│   │   │   │   ├── request_context.py
│   │   │   │   └── security.py
│   │   │   ├── domains/
│   │   │   │   ├── availability/
│   │   │   │   ├── bookings/
│   │   │   │   ├── capacity/
│   │   │   │   ├── catalog/
│   │   │   │   ├── customers/
│   │   │   │   ├── therapists/
│   │   │   │   ├── notifications/
│   │   │   │   └── users/
│   │   │   ├── infrastructure/firestore/
│   │   │   └── integrations/
│   │   │       ├── firebase_auth.py
│   │   │       ├── line_identity.py
│   │   │       ├── line_webhook.py
│   │   │       ├── recaptcha.py
│   │   │       └── cloud_tasks.py
│   │   ├── tests/
│   │   ├── pyproject.toml
│   │   └── Dockerfile
│   └── notification-worker/
│       ├── app/
│       │   ├── main.py
│       │   ├── api/internal.py
│       │   ├── delivery/processor.py
│       │   ├── delivery/classifier.py
│       │   ├── integrations/line_client.py
│       │   ├── templates/
│       │   └── repositories/outbox.py
│       ├── tests/
│       ├── pyproject.toml
│       └── Dockerfile
├── packages/
│   ├── api-client/
│   └── shared-types/
├── infra/terraform/
│   ├── modules/spa-environment/
│   └── environments/{test,prod}/
├── tests/{contract,concurrency,e2e}/
└── Document/
```

## 4. Backend Domain Modules

### 4.1 Core Types

```python
class ActorType(StrEnum):
    GUEST = "GUEST"
    LINE_CUSTOMER = "LINE_CUSTOMER"
    ADMIN_USER = "ADMIN_USER"
    LINE_GROUP_MEMBER = "LINE_GROUP_MEMBER"
    SERVICE = "SERVICE"

class AppRole(StrEnum):
    ADMIN = "ADMIN"
    STAFF = "STAFF"

class BookingStatus(StrEnum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    IN_SERVICE = "IN_SERVICE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"

class BookingSource(StrEnum):
    GUEST_WEB = "GUEST_WEB"
    LIFF = "LIFF"
    ADMIN_WEB = "ADMIN_WEB"

class PricingMode(StrEnum):
    PER_PARTICIPANT = "PER_PARTICIPANT"
    PER_BOOKING = "PER_BOOKING"

class CustomerProfileStatus(StrEnum):
    PROVISIONAL = "PROVISIONAL"
    VERIFIED = "VERIFIED"
    MERGED = "MERGED"

class ConsentPurpose(StrEnum):
    BOOKING_PRIVACY_ACK = "BOOKING_PRIVACY_ACK"
    HEALTH_DATA_EXPLICIT = "HEALTH_DATA_EXPLICIT"
    SECOND_PARTICIPANT_AUTHORIZATION = "SECOND_PARTICIPANT_AUTHORIZATION"

class OutboxState(StrEnum):
    PENDING = "PENDING"
    ENQUEUED = "ENQUEUED"
    PROCESSING = "PROCESSING"
    RETRYABLE = "RETRYABLE"
    SENT = "SENT"
    FAILED = "FAILED"
```

`RequestContext` contains `request_id`, `correlation_id`, `actor_type`, optional protected `actor_id`, `role`, `branch_ids`, `ip_key`, and `user_agent_hash`. It exposes safe log fields that hash or omit protected values.

### 4.2 Domain Services

| Class | Main operations |
| --- | --- |
| `AvailabilityService` | `search(request, context)` |
| `ResourceAllocator` | `allocate(requirements, resources, blocks, bucket_usage)` |
| `BookingService` | `create`, `update`, `confirm`, `cancel`, `start`, `complete`, `mark_no_show` |
| `BookingStateMachine` | `assert_transition(current, command, conditions)` |
| `GuestProtectionService` | `assess_captcha`, `check_rate`, `check_phone_block` |
| `StatusTokenService` | `issue`, `resolve`, `revoke`, `replace` |
| `LineIdentityService` | `verify_id_token`, `link_booking` |
| `LineApprovalService` | `handle_group_confirmation` |
| `OutboxService` | `append_in_transaction`, `enqueue_after_commit` |
| `AdminIdentityService` | `verify_firebase_token`, `bind_invitation`, `authorize` |
| `AuditService` | Build append-only safe audit records |

Domain services depend on repository protocols. They do not import FastAPI request objects or global Firestore clients.

### 4.3 Repository Protocols

```python
class BookingRepository(Protocol):
    async def get_by_public_id(self, public_id: str) -> BookingAggregate | None: ...
    async def list(self, query: BookingListQuery) -> CursorPage[BookingSummary]: ...
    async def run_create(self, command: CreateBookingCommand) -> CreateBookingResult: ...
    async def run_reallocation(self, command: ReallocateBookingCommand) -> BookingAggregate: ...
    async def run_transition(self, command: TransitionCommand) -> BookingAggregate: ...

class CatalogRepository(Protocol):
    async def get_active_variants(self, ids: set[str]) -> list[ServiceVariant]: ...
    async def list_customer_catalog(self, branch_id: str) -> list[CustomerService]: ...

class OutboxRepository(Protocol):
    async def claim(self, event_id: str, lease_until: datetime) -> OutboxEvent | None: ...
    async def mark_sent(self, event_id: str, provider_message_id: str | None) -> None: ...
    async def mark_retryable(self, event_id: str, error: DeliveryError) -> None: ...
    async def mark_failed(self, event_id: str, error: DeliveryError) -> None: ...
```

Firestore implementations live under `infrastructure/firestore/`. Transaction callbacks remain repository-private so all reads-before-writes ordering is enforced in one place.

## 5. API Schemas

### 5.1 Availability Search

Request:

```json
{
  "branchId": "branch_001",
  "dateFrom": "2026-08-15",
  "dateTo": "2026-08-21",
  "participants": [
    {"serviceVariantId": "aroma-therapy-60"}
  ]
}
```

Validation:

- One or two participants
- Date range maximum 31 calendar days
- All variants active and in the branch
- Dates within the configured booking window
- Request body maximum 32 KiB

Response:

```json
{
  "branchId": "branch_001",
  "timezone": "Asia/Bangkok",
  "generatedAt": "2026-08-14T04:00:00Z",
  "slots": [
    {
      "startAt": "2026-08-15T07:00:00Z",
      "localDate": "2026-08-15",
      "localTime": "14:00",
      "estimatedAmountSatang": 60000
    }
  ]
}
```

Resource IDs and remaining unit counts are not public.

### 5.2 Create Booking

Request:

```json
{
  "branchId": "branch_001",
  "startLocal": "2026-08-15T14:00:00+07:00",
  "contact": {
    "phone": "0812345678",
    "participantIndex": 0
  },
  "participants": [
    {
      "nickname": "Som",
      "serviceVariantId": "aroma-therapy-60",
      "health": {
        "hasInformation": true,
        "details": "High blood pressure"
      },
      "healthConsent": {
        "accepted": true,
        "version": "health-consent-th-2026-08"
      }
    }
  ],
  "bookingPrivacyAcknowledgement": {
    "accepted": true,
    "version": "booking-privacy-th-2026-08"
  },
  "secondParticipantAuthorization": null,
  "captchaToken": "opaque-token",
  "lineIdToken": null
}
```

Rules:

- `nickname`: 1–80 characters after normalization
- `phone`: valid Thai or E.164 number and normalized to E.164
- `health.hasInformation`: required boolean
- `health.details`: required when true; prohibited when false; maximum 1,000 characters
- One variant per participant; one/two participants; shared start
- `bookingPrivacyAcknowledgement.accepted` and every participant `healthConsent.accepted` must be true with recognized versions
- `secondParticipantAuthorization.accepted` is required when the submitting contact supplies participant 2 data
- The Couple Package variant requires exactly two participants. Both participants reference one price-bearing line item and the total includes 119,000 satang once.
- Guest requires CAPTCHA; verified LINE submission may still be risk/rate limited but does not require Guest CAPTCHA by default
- `Idempotency-Key` required

Success: `201 Created`

```json
{
  "bookingId": "BK-20260815-001",
  "status": "PENDING",
  "version": 1,
  "summary": {
    "localDate": "2026-08-15",
    "localTime": "14:00",
    "pax": 1,
    "estimatedAmountSatang": 60000
  },
  "statusUrl": "https://<spa-customer-web-run-app-url>/status#t=<opaque-token>"
}
```

The API response is marked `Cache-Control: no-store`.

### 5.3 Resolve Guest Status

Request:

```json
{"token": "opaque-token-from-fragment"}
```

Response:

```json
{
  "bookingId": "BK-20260815-001",
  "status": "CONFIRMED",
  "version": 2,
  "contactPhoneMasked": "081-***-5678",
  "appointment": {
    "localDate": "2026-08-15",
    "localTime": "14:00",
    "timezone": "Asia/Bangkok"
  },
  "participants": [
    {"nickname": "Som", "serviceName": "Aroma Therapy", "durationMinutes": 60}
  ],
  "estimatedAmountSatang": 60000,
  "storeContact": {"phone": "...", "lineUrl": "..."}
}
```

No health flag/detail, LINE User ID, therapist, allocation, audit, internal ID, or cancellation-internal reason is returned.

### 5.4 Admin Transition Command

```json
{
  "expectedVersion": 3,
  "reasonCode": "CUSTOMER_REQUEST",
  "customerMessage": "Your booking was cancelled. Please contact the store for assistance."
}
```

`reasonCode` is required for cancellation and no-show where applicable. `customerMessage` passes an allowlisted length/content validation and never includes health detail.

## 6. Firestore Document Schemas

Fields named `createdAt`, `updatedAt`, and audit timestamps use server timestamps. Every mutable aggregate contains `version`.

### 6.1 `branches/{branchId}`

```json
{
  "name": "SPA 49",
  "active": true,
  "timezone": "Asia/Bangkok",
  "currency": "THB",
  "contactPhone": "+66...",
  "lineContactUrl": "https://line.me/...",
  "mapUrl": "https://maps.google.com/...",
  "address": "...",
  "bookingWindow": {"minDays": 1, "maxDays": 30},
  "slotStepMinutes": 15,
  "defaultBufferMinutes": 0,
  "operatingHours": {
    "MONDAY": [{"open": "10:00", "close": "22:00"}],
    "TUESDAY": [{"open": "10:00", "close": "22:00"}],
    "WEDNESDAY": [{"open": "10:00", "close": "22:00"}],
    "THURSDAY": [{"open": "10:00", "close": "22:00"}],
    "FRIDAY": [{"open": "10:00", "close": "22:00"}],
    "SATURDAY": [{"open": "10:00", "close": "22:00"}],
    "SUNDAY": [{"open": "10:00", "close": "22:00"}]
  },
  "holidays": ["2026-12-31"],
  "version": 1,
  "createdAt": "timestamp",
  "updatedAt": "timestamp"
}
```

`minDays` and `maxDays` use branch-local calendar dates, not rolling 24-hour durations.

### 6.2 `services/{serviceId}`

```json
{
  "branchId": "branch_001",
  "nameTh": "นวดน้ำมันอโรม่า",
  "nameEn": "Aroma Therapy",
  "descriptionTh": "...",
  "descriptionEn": "...",
  "active": true,
  "displayOrder": 10,
  "version": 1,
  "createdAt": "timestamp",
  "updatedAt": "timestamp"
}
```

### 6.3 `service_variants/{variantId}`

```json
{
  "branchId": "branch_001",
  "serviceId": "aroma-therapy",
  "durationMinutes": 60,
  "bufferMinutes": 15,
  "priceSatang": 60000,
  "pricingMode": "PER_PARTICIPANT",
  "requiredPax": 1,
  "catalogVersion": "stitch-customer-v1-2026-08-14",
  "active": true,
  "resourceRequirements": [
    {"resourceType": "BED", "units": 1, "compatibleTags": ["massage"]}
  ],
  "version": 1,
  "createdAt": "timestamp",
  "updatedAt": "timestamp"
}
```

#### 6.3.1 Initial Seed IDs and Variants

The seed manifest uses stable IDs and the approved Business Logic 7.1 bilingual labels:

| Service ID | Variant ID(s): minutes / satang | Pricing mode / required pax |
| --- | --- | --- |
| `complete-relaxation` | `complete-relaxation-105`: 105 / 59000 | `PER_PARTICIPANT` / 1 |
| `couple-relaxation` | `couple-relaxation-90`: 90 / 119000 | `PER_BOOKING` / 2 |
| `foot-reflexology` | `foot-reflexology-60`: 60 / 35000; `foot-reflexology-120`: 120 / 65000 | `PER_PARTICIPANT` / 1 |
| `traditional-thai` | `traditional-thai-60`: 60 / 30000; `traditional-thai-120`: 120 / 60000 | `PER_PARTICIPANT` / 1 |
| `lamenatt-oil` | `lamenatt-oil-60`: 60 / 45000; `lamenatt-oil-120`: 120 / 85000 | `PER_PARTICIPANT` / 1 |
| `tendon-relief` | `tendon-relief-60`: 60 / 45000; `tendon-relief-120`: 120 / 90000 | `PER_PARTICIPANT` / 1 |
| `aroma-therapy` | `aroma-therapy-60`: 60 / 60000; `aroma-therapy-120`: 120 / 120000 | `PER_PARTICIPANT` / 1 |
| `herbal-compress` | `herbal-compress-60`: 60 / 60000; `herbal-compress-120`: 120 / 110000 | `PER_PARTICIPANT` / 1 |
| `body-scrub` | `body-scrub-60`: 60 / 60000 | `PER_PARTICIPANT` / 1 |
| `herbal-steam` | `herbal-steam-30`: 30 / 30000 | `PER_PARTICIPANT` / 1 |
| `hot-compress-neck-shoulder-back` | `hot-compress-neck-shoulder-back-20`: 20 / 19000 | `PER_PARTICIPANT` / 1 |

The seed file is `SPA/infra/seed/service-catalog.v1.json`. It contains 11 services and 17 variants. Seed application creates missing records and reports drift; it does not silently overwrite Admin changes.

### 6.4 `resources/{resourceId}`

```json
{
  "branchId": "branch_001",
  "name": "Bed 1",
  "resourceType": "BED",
  "capacityUnits": 1,
  "tags": ["massage", "aroma"],
  "allocationPriority": 10,
  "active": true,
  "version": 1,
  "createdAt": "timestamp",
  "updatedAt": "timestamp"
}
```

### 6.5 `resource_blocks/{blockId}`

```json
{
  "branchId": "branch_001",
  "resourceId": "bed_001",
  "startAt": "timestamp",
  "endAt": "timestamp",
  "reason": "Maintenance",
  "active": true,
  "createdBy": "firebaseUid",
  "version": 1,
  "createdAt": "timestamp",
  "updatedAt": "timestamp"
}
```

A null `resourceId` represents a branch-wide closure; holidays remain branch configuration for full-day closure.

### 6.6 `capacity_buckets/{bucketId}`

Document ID: `<branchId>_<resourceId>_<YYYYMMDD>_<HHmm>` in branch local time.

```json
{
  "branchId": "branch_001",
  "resourceId": "bed_001",
  "localDate": "2026-08-15",
  "localTime": "14:00",
  "bucketStartAt": "timestamp",
  "usedUnits": 1,
  "version": 4,
  "updatedAt": "timestamp"
}
```

The capacity limit is read from the latest resource document. `usedUnits` must never be negative. A zero-used bucket may be retained for transaction simplicity and removed later by maintenance.

### 6.7 `bookings/{bookingDocId}`

```json
{
  "publicBookingId": "BK-20260815-001",
  "branchId": "branch_001",
  "source": "GUEST_WEB",
  "status": "PENDING",
  "contact": {
    "participantId": "participant-id",
    "phoneE164": "+66812345678",
    "phoneMasked": "081-***-5678",
    "phoneKey": "hmac-hex"
  },
  "startAt": "timestamp",
  "endAt": "timestamp",
  "localDate": "2026-08-15",
  "localStartTime": "14:00",
  "timezone": "Asia/Bangkok",
  "pax": 1,
  "estimatedAmountSatang": 60000,
  "healthAlert": true,
  "lineLinked": false,
  "assignmentState": "UNASSIGNED",
  "capacityReleased": false,
  "bookingPrivacyConsentReceiptId": "consent-receipt-id",
  "version": 1,
  "createdAt": "timestamp",
  "updatedAt": "timestamp",
  "confirmedAt": null,
  "cancelledAt": null,
  "completedAt": null
}
```

Cancellation reason fields are added only on cancellation and have separate internal/customer-safe values.

### 6.8 `booking_line_items/{lineItemId}`

```json
{
  "bookingDocId": "internal-booking-id",
  "branchId": "branch_001",
  "serviceSnapshot": {
    "serviceId": "aroma-therapy",
    "variantId": "aroma-therapy-60",
    "nameTh": "นวดน้ำมันอโรม่า",
    "nameEn": "Aroma Therapy",
    "durationMinutes": 60,
    "bufferMinutes": 15,
    "pricingMode": "PER_PARTICIPANT",
    "requiredPax": 1,
    "unitPriceSatang": 60000
  },
  "quantity": 1,
  "lineTotalSatang": 60000,
  "participantIds": ["participant-id"],
  "createdAt": "timestamp"
}
```

For `PER_BOOKING`, `quantity` is always `1`; `participantIds` contains exactly `requiredPax` IDs. The Couple Package therefore has two participant IDs and one `lineTotalSatang=119000`. Booking totals are the sum of `lineTotalSatang`, never participant count multiplied by a `PER_BOOKING` price.

### 6.9 `booking_participants/{participantId}`

```json
{
  "bookingDocId": "internal-booking-id",
  "branchId": "branch_001",
  "sequence": 1,
  "nickname": "Som",
  "customerId": "customer-id",
  "lineItemId": "line-item-id",
  "assignment": {
    "therapistId": null,
    "assignedAt": null,
    "assignedBy": null
  },
  "version": 1,
  "createdAt": "timestamp",
  "updatedAt": "timestamp"
}
```

### 6.10 `participant_health/{participantId}`

```json
{
  "bookingDocId": "internal-booking-id",
  "branchId": "branch_001",
  "customerId": "customer-id",
  "sourceHealthProfileVersion": 3,
  "hasInformation": true,
  "details": "High blood pressure",
  "healthConsentReceiptId": "consent-receipt-id",
  "snapshotState": "DRAFT",
  "retentionPolicyVersion": "health-3y-proposed-v1",
  "retentionAnchorAt": "timestamp",
  "expiresAt": "timestamp-plus-3-years",
  "version": 1,
  "createdAt": "timestamp",
  "updatedAt": "timestamp"
}
```

This collection is never joined into public or notification projections. `ADMIN`/`STAFF` may correct it while the Booking is active; transition to `COMPLETED` sets `snapshotState=FINAL`, after which the historical snapshot is immutable. Audit changes store only `hasInformation` and `healthChanged`, not `details`.

### 6.11 Customer Profile, Health Profile, Consent, and Merge Documents

`customers/{customerId}`:

```json
{
  "status": "PROVISIONAL",
  "primaryNickname": "Som",
  "phoneE164": "+66812345678",
  "phoneMasked": "081-***-5678",
  "phoneKey": "hmac-hex",
  "verifiedLineLinked": false,
  "mergedIntoCustomerId": null,
  "lastCompletedAt": null,
  "version": 1,
  "createdAt": "timestamp",
  "updatedAt": "timestamp"
}
```

`customer_identity_links/{provider_lineUserIdHash}` stores the restricted raw verified LINE User ID, Provider/Channel IDs, `customerId`, verification time, active state, and version. The deterministic document key is a keyed hash; phone is never an identity-link key.

`customer_health_profiles/{customerId}`:

```json
{
  "hasInformation": true,
  "details": "High blood pressure",
  "activeConsentReceiptId": "consent-receipt-id",
  "lastCollectedOrUpdatedAt": "timestamp",
  "lastCompletedAt": "timestamp",
  "retentionAnchorAt": "timestamp",
  "retentionPolicyVersion": "health-3y-proposed-v1",
  "expiresAt": "timestamp-plus-3-years",
  "version": 3,
  "createdAt": "timestamp",
  "updatedAt": "timestamp"
}
```

`retentionAnchorAt` is `max(lastCompletedAt, lastCollectedOrUpdatedAt)`. The proposed job sets `expiresAt = retentionAnchorAt + 3 years`; production must not enable the TTL field until the policy version is approved.

`consent_receipts/{consentReceiptId}`:

```json
{
  "purpose": "HEALTH_DATA_EXPLICIT",
  "wordingVersion": "health-consent-th-2026-08",
  "wordingSha256": "hex",
  "bookingDocId": "internal-booking-id",
  "participantId": "participant-id",
  "customerId": "customer-id",
  "captureChannel": "GUEST_WEB",
  "accepted": true,
  "acceptedAt": "timestamp",
  "withdrawnAt": null,
  "withdrawalWorkflowId": null,
  "evidenceExpiresAt": null,
  "createdAt": "timestamp"
}
```

`customer_profile_merges/{mergeId}` stores source/target Customer IDs, verified actor, reason, source versions, safe changed-field names, time, and reversal status. It stores no plaintext health detail. The source Customer becomes `MERGED`; all subsequent reads resolve the target.

### 6.12 `resource_reservations/{reservationId}`

```json
{
  "bookingDocId": "internal-booking-id",
  "participantId": "participant-id",
  "branchId": "branch_001",
  "resourceId": "bed_001",
  "resourceType": "BED",
  "units": 1,
  "bucketIds": ["branch_001_bed_001_20260815_1400"],
  "startAt": "timestamp",
  "releaseAt": "timestamp",
  "active": true,
  "releasedAt": null,
  "version": 1,
  "createdAt": "timestamp",
  "updatedAt": "timestamp"
}
```

### 6.13 Identity and Access Documents

`app_users/{firebaseUid}`:

```json
{
  "email": "staff@example.com",
  "displayName": "Staff Name",
  "role": "STAFF",
  "active": true,
  "branchIds": ["branch_001"],
  "invitedBy": "adminUid",
  "lastLoginAt": "timestamp",
  "version": 1,
  "createdAt": "timestamp",
  "updatedAt": "timestamp"
}
```

`app_user_invitations/{emailHash}` stores normalized email, intended role, branch IDs, expiry, inviter, consumed Firebase UID, and audit timestamps. Invitation default validity is seven days.

`line_groups/{groupId}` stores display label, active state, environment, registration actor/time, and last valid event time. Channel secrets are not stored here.

### 6.14 Guest and LINE Link Documents

`guest_status_tokens/{sha256Token}`:

```json
{
  "bookingDocId": "internal-booking-id",
  "active": true,
  "issuedAt": "timestamp",
  "expiresAt": "timestamp",
  "revokedAt": null,
  "replacedByDigest": null
}
```

`line_booking_links/{bookingDocId}`:

```json
{
  "bookingDocId": "internal-booking-id",
  "customerId": "customer-id",
  "lineUserId": "trusted-provider-user-id",
  "providerId": "configured-provider-id",
  "channelId": "configured-login-channel-id",
  "verifiedAt": "timestamp",
  "linkedAt": "timestamp",
  "active": true,
  "version": 1
}
```

Raw LINE User IDs are permitted only in this restricted document and audit when required. Logs use a keyed hash.

### 6.15 Guard and Idempotency Documents

`phone_booking_guards/{branchId_phoneKey}`:

```json
{
  "branchId": "branch_001",
  "phoneKey": "hmac-hex",
  "activePendingCount": 1,
  "version": 3,
  "updatedAt": "timestamp"
}
```

`booking_duplicate_guards/{guardKey}` uses a digest of branch, phone key, local date, and local start time. It stores Booking reference, capacity-consuming status, and updated time. It exists while the Booking is `PENDING`, `CONFIRMED`, or `IN_SERVICE`.

`idempotency_records/{scopeDigest}`:

```json
{
  "endpoint": "POST:/api/v1/public/bookings",
  "callerKey": "hmac-derived",
  "idempotencyKey": "uuid",
  "payloadDigest": "sha256",
  "state": "COMPLETED",
  "statusCode": 201,
  "response": {"bookingId": "BK-...", "status": "PENDING"},
  "expiresAt": "timestamp",
  "createdAt": "timestamp",
  "updatedAt": "timestamp"
}
```

The stored success response includes the raw status token only if the idempotency record is protected as restricted server-only data. It is removed by TTL after 24 hours.

### 6.16 Outbox and Audit Documents

`notification_outbox/{eventId}`:

```json
{
  "eventType": "CUSTOMER_CONFIRMED",
  "aggregateType": "BOOKING",
  "aggregateId": "internal-booking-id",
  "bookingPublicId": "BK-...",
  "targetType": "CUSTOMER_LINE",
  "state": "PENDING",
  "templateVersion": 1,
  "providerRetryKey": "stable-uuid",
  "enqueueGeneration": 1,
  "attemptCount": 0,
  "nextAttemptAt": "timestamp",
  "leaseOwner": null,
  "leaseExpiresAt": null,
  "lastErrorCode": null,
  "correlationId": "uuid",
  "createdAt": "timestamp",
  "updatedAt": "timestamp",
  "sentAt": null
}
```

`audit_events/{eventId}`:

```json
{
  "eventType": "BOOKING_STATUS_CHANGED",
  "entityType": "BOOKING",
  "entityId": "internal-booking-id",
  "bookingPublicId": "BK-...",
  "actorType": "LINE_GROUP_MEMBER",
  "actorId": "line-user-id-or-firebase-uid",
  "actorGroupId": "line-group-id-or-null",
  "fromState": "PENDING",
  "toState": "CONFIRMED",
  "changeSummary": {"fields": ["status"], "healthChanged": false},
  "reasonCode": null,
  "requestId": "uuid",
  "correlationId": "uuid",
  "occurredAt": "timestamp",
  "expiresAt": "timestamp-plus-400-days"
}
```

Audit documents are append-only. No health detail or token is stored.

## 7. Firestore Index and TTL Files

`firestore.indexes.json` includes the composite intents defined in TDD. The implementation must include at least:

```json
{
  "indexes": [
    {
      "collectionGroup": "bookings",
      "queryScope": "COLLECTION",
      "fields": [
        {"fieldPath": "branchId", "order": "ASCENDING"},
        {"fieldPath": "status", "order": "ASCENDING"},
        {"fieldPath": "startAt", "order": "ASCENDING"}
      ]
    },
    {
      "collectionGroup": "notification_outbox",
      "queryScope": "COLLECTION",
      "fields": [
        {"fieldPath": "state", "order": "ASCENDING"},
        {"fieldPath": "nextAttemptAt", "order": "ASCENDING"}
      ]
    }
  ],
  "fieldOverrides": []
}
```

Terraform configures TTL fields:

- `guest_status_tokens.expiresAt`
- `idempotency_records.expiresAt`
- `abuse_counters.expiresAt`
- `webhook_events.expiresAt`
- `notification_attempts.expiresAt`
- `audit_events.expiresAt`
- `participant_health.expiresAt` only after approval of `health-3y-proposed-v1` or its replacement
- `customer_health_profiles.expiresAt` only after the same approval
- `consent_receipts.evidenceExpiresAt` after the approved withdrawal/deletion evidence period is calculated

Firestore security rules are intentionally closed:

```text
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /{document=**} {
      allow read, write: if false;
    }
  }
}
```

## 8. Time and Bucket Functions

```python
BUCKET_MINUTES = 15

def required_bucket_starts(start_at, duration_minutes, buffer_minutes):
    assert start_at is aligned to 15 minutes in branch timezone
    occupied_minutes = duration_minutes + buffer_minutes
    bucket_count = ceil(occupied_minutes / BUCKET_MINUTES)
    return [start_at + i * 15 minutes for i in range(bucket_count)]
```

Operating-hour validation compares the service duration excluding buffer to the customer-visible close policy, then includes buffer for capacity. The branch may choose whether buffer is allowed after closing; Phase 1 default is **no**, so duration plus buffer must fit the operating interval.

Advance window:

```text
earliestLocalDate = todayInBranch + minDays
latestLocalDate   = todayInBranch + maxDays
```

The selected local date must be inclusive within the range. Daylight-saving ambiguity is not expected in Asia/Bangkok, but conversion uses IANA timezone libraries rather than a hard-coded offset.

## 9. Availability Algorithm

```text
function searchAvailability(request):
    branch = loadActiveBranch(request.branchId)
    variants = loadActiveVariants(request.participants.variantIds)
    validateDateRange(branch, request.dateFrom, request.dateTo)

    results = []
    for localDate in requestedDates:
        for localStart in generate15MinuteStarts(branch, localDate):
            requirements = buildRequirements(variants, localStart)
            candidateResources = loadCompatibleActiveResources(requirements)
            overlappingBlocks = loadBlocks(candidateResources, requirements.interval)
            bucketUsage = batchReadCapacityBuckets(candidateResources, requirements.buckets)

            allocation = deterministicAllocate(
                requirements,
                candidateResources,
                overlappingBlocks,
                bucketUsage
            )
            if allocation is complete:
                results.append(customerSafeSlot(localStart, variants))
    return results
```

The availability response is advisory. Cache customer-safe catalogue/config for up to five minutes, but do not cache capacity usage across requests. A single search range is limited to 31 days and the result to configured operating slots.

## 10. Deterministic Resource Allocation

```text
function deterministicAllocate(requirements, resources, blocks, bucketUsage):
    nodes = expand requirements by participant and resource type
    sort nodes by fewest compatible candidates, then participant sequence

    function dfs(nodeIndex, provisionalUsage, assignments):
        if nodeIndex == nodes.length:
            return assignments

        node = nodes[nodeIndex]
        candidates = compatible resources that are active and not blocked
        sort candidates by:
            allocationPriority ascending,
            remainingCapacityAfterAllocation ascending,
            resourceId ascending

        for candidate in candidates:
            if every required bucket has enough capacity after provisional usage:
                reserve provisionally
                result = dfs(next node, provisionalUsage, assignments)
                if result found: return result
                undo provisional reservation
        return no allocation

    return dfs(0, copy(bucketUsage), [])
```

The transaction callback reruns this algorithm after reading current resources, blocks, and buckets. Candidate lists are capped at 50 active resources per type in Phase 1; exceeding the cap is an operational configuration error requiring review.

## 11. Create Booking Transaction Pseudocode

```text
function createBooking(command, context):
    normalized = validateAndNormalize(command)
    validateRecognizedConsentVersions(normalized)
    lineItems = buildPriceBearingLineItems(normalized.participants)
    require every PER_BOOKING line item has exactly requiredPax participants
    identity = verifyOptionalLineToken(normalized.lineIdToken)
    protection = checkGuestProtectionIfNeeded(normalized, context)
    idempotency = findIdempotency(context, command.key)

    if idempotency.completedWithSameDigest:
        return storedResponse
    if idempotency.existsWithDifferentDigest:
        raise IDEMPOTENCY_CONFLICT

    rawStatusToken = secureRandom(32 bytes)
    statusDigest = sha256(rawStatusToken)

    transaction callback:
        read branch, variants, resources, blocks
        read verified Customer identity/profile when LINE linked
        read phone block and rate/booking guard documents
        read duplicate guard
        read all candidate capacity buckets
        read daily Booking counter
        read idempotency document

        validate branch rules and active records again
        require activePendingCount < configured maximum
        require duplicate guard absent
        allocation = deterministicAllocate(current transaction snapshot)
        require complete allocation

        publicId = incrementAndFormatAppointmentDateCounter()
        resolve verified Customer Profile or create provisional Guest profiles
        create Booking and charge-once Booking line-item documents
        create participant and DRAFT Booking Health Snapshot documents
        update current Customer Health Profiles
        create independent versioned consent receipt documents
        create reservation documents
        increment all bucket usedUnits and versions
        increment phone activePendingCount
        create duplicate guard
        create status-token digest
        create optional verified LINE link
        append audit event
        append ADMIN_NEW_BOOKING outbox event
        if LINE linked: append CUSTOMER_PENDING outbox event
        store completed idempotency response including one-time status token

    enqueue outbox event IDs best effort
    return response with status URL fragment
```

All transaction reads are issued before the first write. Any missing expected document or failed capacity condition aborts the transaction without partial records.

Booking ID formatting uses the branch-local appointment date at creation and pads to at least three digits. Sequence 1,000 becomes `1000`; it is never truncated. The public ID remains unchanged if the appointment is later rescheduled.

## 12. Transition Algorithms

### 12.1 Confirm

```text
transaction:
    read Booking and phone_booking_guard
    require Booking.status == PENDING
    update status=CONFIRMED, confirmedAt, version+1
    decrement activePendingCount exactly once
    update duplicate guard status=CONFIRMED
    append audit
    append CUSTOMER_CONFIRMED outbox if LINE linked
    append ADMIN_CONFIRM_RESULT outbox for group confirmation
```

Admin Web confirmation supplies `expectedVersion`; group confirmation compares only the status. The first commit wins.

### 12.2 Cancel

```text
transaction:
    read Booking, reservations, buckets, guards
    require status in PENDING or CONFIRMED
    require reason
    decrement each active reservation bucket
    mark each reservation inactive and released
    if previous status PENDING: decrement activePendingCount
    remove duplicate guard
    set CANCELLED, capacityReleased=true, version+1
    append audit and customer-safe cancellation outbox
```

### 12.3 Start

Require `CONFIRMED` and one active therapist assignment per participant. Transition to `IN_SERVICE`; reservations remain active.

### 12.4 Complete or No-show

Read and release capacity exactly as cancellation, set terminal status, update duplicate guard, and append audit. On `COMPLETED`, finalize every Booking Health Snapshot, update each Customer Profile `lastCompletedAt`, recalculate the proposed three-year retention anchor/expiry, and preserve current Health Profile content. `NO_SHOW` does not pretend a completed visit occurred; its health retention anchor remains the latest authorized health collection/update. No-show is valid only from `CONFIRMED` and at/after the configured operational threshold, initially appointment start time.

## 13. Capacity-safe Booking Edit

```text
transaction:
    read Booking/version, old reservations, old buckets
    read new variants/resources/blocks/new buckets
    read old/new phone guards and duplicate guards if contact/time changes
    require expectedVersion matches
    compute complete new allocation without mutating old bucket state
    require allocation available considering own old units

    decrement buckets no longer used
    adjust buckets retained or changed
    increment newly used buckets
    replace/mark reservation documents
    move phone Pending counter if needed
    move duplicate guard if phone/date/time changed
    update Booking/participants/health snapshots and version
    append audit and BOOKING_UPDATED outbox
```

When evaluating a bucket currently held by the same Booking, subtract its old units from `usedUnits` before testing the new requirement. No mutation is committed unless the whole new allocation succeeds.

## 14. Guest Protection Algorithms

### 14.1 Enforcement Keys

```text
phoneKey = HMAC-SHA256(activePepper, canonicalE164Phone)
ipKey    = HMAC-SHA256(activePepper, canonicalTrustedClientIp)
```

Store pepper version with counters so rotation can check active and immediately previous versions during a bounded transition.

### 14.2 Sliding Windows

Phase 1 uses fixed-window documents for predictable Firestore cost:

```text
abuse_counters/{subjectType}_{subjectKey}_{windowStartEpoch}
```

The transaction increments the current 15-minute/hour/day documents and checks limits. Counter documents receive `expiresAt = windowEnd + 48 hours`.

Booking guards are separate from attempt counters and have no automatic expiry while a matching Booking remains active.

### 14.3 reCAPTCHA

`RecaptchaVerifier.assess(token, expected_action, site_key, client_ip)` requires:

- Token valid
- Expected action equals `booking_submit`
- Expected site key/hostname for the environment
- Risk score at or above configured threshold

Failure returns a generic `CAPTCHA_REJECTED`; provider details remain in safe security logs.

## 15. Status Token Resolution

```text
function resolveStatus(rawToken, context):
    apply resolution rate limit
    require base64url token with expected length
    digest = sha256(rawToken)
    tokenDoc = get guest_status_tokens/digest
    require active and now < expiresAt
    booking = get Booking and participants
    return PublicStatusProjection.build(booking, participants, branch)
```

Responses use `Cache-Control: no-store, private`, `Pragma: no-cache`, and never set the raw token in a cookie. Replacement atomically revokes the old digest and creates the new digest.

## 16. Admin Identity and Permission Dependencies

FastAPI dependencies:

```python
async def current_admin_user(authorization: str) -> AdminPrincipal: ...

def require_permissions(*permissions: Permission):
    async def dependency(principal: AdminPrincipal = Depends(current_admin_user)):
        if not principal.active or not permissions <= principal.permissions:
            raise PermissionDenied()
        return principal
    return dependency
```

Login binding:

1. Verify Firebase ID token and verified email.
2. Load `app_users/{uid}`; return if active.
3. Load unconsumed `app_user_invitations/{emailHash}`.
4. In a transaction, require invitation valid/unconsumed, create `app_users/{uid}`, mark invitation consumed, and append audit.
5. Do not derive role from a client claim.

User disable sets both `app_users.active=false` and disables the Firebase user. The Firestore active check provides immediate application denial even if a token remains cryptographically valid.

### 16.1 Health Profile Update, Merge, and Consent Withdrawal

- `PATCH health-profile` reads `expectedVersion`, writes the new current Profile, recalculates `retentionAnchorAt/expiresAt`, and appends a safe audit summary. It does not modify any `FINAL` Booking Health Snapshot.
- `POST customer:merge` requires `customer.merge`, a reason, source/target expected versions, and explicit staff verification. It rejects cyclic/already-conflicting merges and phone-only automation.
- Consent withdrawal marks the receipt withdrawn and creates a privacy-workflow record with `PENDING_REVIEW`. Authorized staff evaluates active Bookings and documented legal holds, then restricts, deletes, or anonymizes eligible health data. The workflow and outcome are audited without copying health detail.
- Public endpoints do not expose these operations in Phase 1; a customer contacts the store to exercise rights.

## 17. LINE Webhook Handler

```text
receive raw body and x-line-signature
verify signature with endpoint-specific channel secret
parse events
for each event:
    derive webhook dedupe key
    if already processed: acknowledge
    persist RECEIVED dedupe record

    if admin group confirmation message:
        require source.type == group
        require source.groupId registered and active
        require source.userId present
        parse exact command: "CONFIRM <publicBookingId> v1"
        run atomic confirm
        persist processing result
    else:
        process supported customer/link event or safely ignore

return HTTP 200 promptly
```

Unsupported commands do not alter state. Provider reply tokens are not persisted. Group result messages are sent through the outbox to avoid relying on a short-lived reply token.

## 18. Notification Worker

### 18.1 Task Handler

```text
validate Cloud Run/IAM caller
validate eventId format
transactionally claim event if state is dispatchable or lease expired
if event already SENT or FAILED: return 204

load customer-safe Booking projection and target configuration
render versioned template
send through correct LINE channel with X-Line-Retry-Key=event.providerRetryKey

if success or LINE reports the same retry key was already accepted:
    transactionally mark SENT and append attempt
    return 204
if permanent provider failure:
    transactionally mark FAILED and append attempt
    return 204
if transient failure and attempt budget remains:
    transactionally mark RETRYABLE and append attempt
    return 503 with optional Retry-After
if attempt count reaches 8 or delivery age reaches 24 hours:
    transactionally mark FAILED and append attempt
    return 204
```

### 18.2 Error Classification

| Class | Examples | Worker behavior |
| --- | --- | --- |
| Success | Provider accepted request, or retry key already accepted | `SENT`, `2xx` |
| Permanent | Invalid target, blocked/unreachable user where provider confirms permanence, invalid template | `FAILED`, `2xx`, Admin alert |
| Retryable | Timeout, connection error, provider 429, provider 5xx | `RETRYABLE`, non-`2xx` |
| Configuration | Missing secret, channel mismatch | `FAILED`, `2xx`, high-priority alert |

Provider response bodies are redacted before storage. `notification_attempts` records safe provider code, latency, attempt number, and expiry.

### 18.3 Reconciliation

The scheduled endpoint queries up to 100 stale events ordered by eligibility, including eligible `RETRYABLE` events. It marks expired/exhausted events `FAILED`. For dispatchable events it uses a task name derived from `eventId + enqueueGeneration`; the same generation is safe to retry, while recovery after a missing/deleted task atomically increments the generation. It updates the event to `ENQUEUED` only when task creation succeeds or the same-generation task already exists. It never sends LINE directly.

### 18.4 Operational Alert Bridge

Cloud Monitoring publishes alert incidents to `spa-ops-alerts`. An authenticated Pub/Sub push request invokes `/internal/v1/ops-alerts`. The Worker validates the OIDC caller/audience, deduplicates by incident ID and state, renders `admin_ops_alert_v1`, and pushes only to the Group ID loaded from `spa-line-admin-group-id`. The payload uses service, severity, safe condition summary, incident state, start time, and console deep link; it rejects health, phone, token, request-body, and credential fields. No alternate Phase 1 alert destination is implemented.

## 19. Notification Template Contracts

Template identifiers:

- `admin_new_booking_v1`
- `admin_confirmation_result_v1`
- `customer_pending_v1`
- `customer_confirmed_v1`
- `customer_updated_v1`
- `customer_cancelled_v1`
- `admin_ops_alert_v1`

Render input is a typed safe projection:

```python
class NotificationBookingView(BaseModel):
    public_booking_id: str
    status: BookingStatus
    contact_nickname: str
    contact_phone_display: str
    local_date_label: str
    local_time: str
    participants: list[NotificationParticipantView]
    pax: int
    estimated_amount_satang: int
    health_alert: bool
    map_url: str | None
```

Customer template builders do not accept `health_alert` or health detail fields. Admin group builder accepts only the boolean `health_alert`. Template snapshot tests validate LINE Flex limits and prohibit protected keys recursively.

## 20. Frontend State and API Use

### 20.1 Customer Web

`BookingDraft` is kept in memory plus `sessionStorage`; it is cleared after successful creation. It contains no LINE token after submit and no status token except on the result/status route.

```ts
type BookingDraft = {
  branchId: string;
  participants: Array<{
    nickname: string;
    serviceVariantId: string;
    health: { hasInformation: boolean; details?: string };
    healthConsent: { accepted: boolean; version: string };
  }>;
  startLocal?: string;
  phone?: string;
  bookingPrivacyAcknowledgement?: { accepted: boolean; version: string };
  secondParticipantAuthorization?: { accepted: boolean; version: string };
};
```

The result page replaces browser history so accidental Back/Resubmit does not create a second Booking. A UUID idempotency key is generated when entering Review and remains stable for retries of the same draft.

The status page reads `location.hash`, removes the token from visible history with `history.replaceState`, keeps it only in memory, and POSTs it to the resolve endpoint.

### 20.2 Admin Web

Firebase authentication state is held by the Firebase SDK. The API client obtains a current ID token per request and retries once after forced refresh on `401`, never on `403`.

Route access:

- Any active role: booking, calendar, service, capacity, therapist, notification operational pages
- `ADMIN` only: users, roles, security, LINE groups, global audit

Admin mutation forms always send `expectedVersion` and surface `RESOURCE_VERSION_CONFLICT` by reloading current data before allowing another save.

### 20.3 Generated Client

CI exports FastAPI OpenAPI JSON and generates `packages/api-client`. Generated files are never edited manually. A drift check fails when API changes are not regenerated.

## 21. Problem Response Mapping

| Domain exception | HTTP | Code |
| --- | ---: | --- |
| Payload/schema invalid | 422 | `VALIDATION_FAILED` |
| Required consent absent/version unknown | 422 | `CONSENT_REQUIRED` / `CONSENT_VERSION_UNRECOGNIZED` |
| Missing/invalid auth | 401 | `AUTHENTICATION_REQUIRED` / `AUTHENTICATION_INVALID` |
| Active user lacks permission | 403 | `PERMISSION_DENIED` |
| CAPTCHA fails | 403 | `CAPTCHA_REJECTED` |
| Guest rate exceeded | 429 | `RATE_LIMITED` |
| Duplicate/active Pending guard | 409 | `DUPLICATE_BOOKING` / `ACTIVE_PENDING_LIMIT` |
| Capacity no longer available | 409 | `CAPACITY_UNAVAILABLE` |
| Stale version/idempotency conflict | 409 | `RESOURCE_VERSION_CONFLICT` / `IDEMPOTENCY_CONFLICT` |
| Status token invalid or expired | 404 / 410 | `STATUS_TOKEN_INVALID` / `STATUS_TOKEN_EXPIRED` |
| Invalid state command | 409 | `INVALID_STATE_TRANSITION` |
| Customer merge is stale/conflicting | 409 | `CUSTOMER_PROFILE_MERGE_CONFLICT` |
| Unexpected provider/dependency failure | 503 | `DEPENDENCY_UNAVAILABLE` |
| Unexpected application failure | 500 | `INTERNAL_ERROR` |

Stack traces are never returned. `requestId` is always included.

## 22. Configuration Models

### 22.1 SPA API Settings

```text
APP_ENV
GCP_PROJECT_ID=the49-487609
GCP_REGION=asia-southeast1
FIRESTORE_DATABASE=spa
DEFAULT_BRANCH_ID
BOOKING_BASE_URL
ADMIN_BASE_URL
API_BASE_URL
CORS_ALLOWED_ORIGINS
FIREBASE_PROJECT_ID=the49-487609
LINE_PROVIDER_ID_SECRET_NAME=spa-line-provider-id
LINE_CUSTOMER_LOGIN_CHANNEL_ID_SECRET_NAME=spa-line-customer-login-channel-id
LINE_CUSTOMER_LOGIN_CHANNEL_SECRET_NAME=spa-line-customer-login-channel-secret
LINE_CUSTOMER_LIFF_ID_SECRET_NAME=spa-line-customer-liff-id
LINE_CUSTOMER_MESSAGING_CHANNEL_ID_SECRET_NAME=spa-line-customer-messaging-channel-id
LINE_CUSTOMER_MESSAGING_CHANNEL_SECRET_NAME=spa-line-customer-messaging-channel-secret
LINE_ADMIN_MESSAGING_CHANNEL_ID_SECRET_NAME=spa-line-admin-messaging-channel-id
LINE_ADMIN_MESSAGING_CHANNEL_SECRET_NAME=spa-line-admin-messaging-channel-secret
LINE_ADMIN_GROUP_ID_SECRET_NAME=spa-line-admin-group-id
RECAPTCHA_PROJECT_ID
RECAPTCHA_SITE_KEY
RECAPTCHA_SCORE_THRESHOLD=0.5
TASK_QUEUE_NAME=spa-line-notifications
TASK_QUEUE_REGION=asia-southeast1
WORKER_TASK_URL
WORKER_TASK_AUDIENCE
PHONE_IP_PEPPER_SECRET_NAME
CAPACITY_BUCKET_MINUTES=15
IDEMPOTENCY_TTL_HOURS=24
ACTIVE_PENDING_PER_PHONE=2
HEALTH_RETENTION_YEARS=3
HEALTH_RETENTION_POLICY_VERSION=health-3y-proposed-v1
HEALTH_RETENTION_POLICY_APPROVED=false
```

### 22.2 Worker Settings

```text
APP_ENV
GCP_PROJECT_ID=the49-487609
GCP_REGION=asia-southeast1
FIRESTORE_DATABASE=spa
LINE_CUSTOMER_MESSAGING_CHANNEL_ACCESS_TOKEN_SECRET_NAME=spa-line-customer-messaging-channel-access-token
LINE_ADMIN_MESSAGING_CHANNEL_ACCESS_TOKEN_SECRET_NAME=spa-line-admin-messaging-channel-access-token
LINE_ADMIN_GROUP_ID_SECRET_NAME=spa-line-admin-group-id
OUTBOX_LEASE_SECONDS=120
OUTBOX_RECONCILE_BATCH=100
NOTIFICATION_ATTEMPT_TTL_DAYS=90
OPS_ALERT_TOPIC=spa-ops-alerts
```

### 22.3 Frontend Public Settings

Only public identifiers may use `NEXT_PUBLIC_*`: API base URL, Firebase public web config, LIFF ID, reCAPTCHA site key, and environment label. No channel secret, access token, service credential, pepper, or internal worker URL is public.

Production startup fails when required settings or secret versions are missing. It also fails while `HEALTH_RETENTION_POLICY_APPROVED=false`; three years is a proposed value, not implicit approval.

## 23. Terraform Layout and Resources

```text
infra/terraform/
├── modules/spa-environment/
│   ├── apis.tf
│   ├── artifact_registry.tf
│   ├── firestore.tf
│   ├── firebase.tf
│   ├── iam.tf
│   ├── run.tf
│   ├── tasks.tf
│   ├── scheduler.tf
│   ├── recaptcha.tf
│   ├── secrets.tf
│   ├── monitoring.tf
│   ├── backups.tf
│   ├── variables.tf
│   └── outputs.tf
└── environments/
    ├── test/{main.tf,backend.tf,terraform.tfvars}
    └── prod/{main.tf,backend.tf,terraform.tfvars}
```

Terraform targets the existing project `the49-487609`; it does not create or re-associate the project or Firebase application. Production manages:

- Required API activation
- Artifact Registry repositories
- Named Firestore Native database `spa` in `asia-southeast1` with delete protection, plus indexes/fields/TTL where provider support is available
- SPA authorization documents and documented Firebase Auth provider/bootstrap inputs while reusing the existing Firebase project
- Four Cloud Run v2 services and dedicated service accounts
- Cloud Tasks queue and Scheduler reconciliation job
- reCAPTCHA key and service access
- Import and IAM bindings for the 11 existing `spa-line-*` Secret Manager containers, but no secret versions or plaintext values in state
- Cloud Run invoker bindings for Task/Scheduler principals
- Pub/Sub topic `spa-ops-alerts`, authenticated push subscription, and Worker invoker binding for LINE-Group-only operational alerts
- Monitoring dashboards and alert policies
- Daily Firestore backup schedule with 30-day retention
- Workload Identity Pool/provider and deployer bindings

Terraform state uses separate `test` and `prod` state prefixes in a protected, versioned GCS backend in `the49-487609`. Production apply requires protected GitHub Environment approval. Test resources use `spa-*-test` names and never share the `spa` production database or production LINE secrets.

## 24. Cloud Run Container Contracts

### 24.1 API and Worker

- Multi-stage container build
- Non-root runtime user
- Listen on `$PORT`
- Uvicorn with process count tuned to allocated CPU; start with one process and Cloud Run concurrency
- `/health/live` performs no dependency call
- `/health/ready` validates startup configuration and initialized clients without performing expensive writes
- Graceful SIGTERM handling; stop accepting new work and complete bounded in-flight requests
- Read-only image filesystem assumptions; `/tmp` only for ephemeral library needs

### 24.2 Frontends

- Next.js standalone output
- Non-root runtime
- No server-side secret beyond optional service configuration; frontend runtime does not access Firestore
- Immutable static assets with hashed cache headers
- Dynamic booking/status/admin HTML and API-sensitive responses use appropriate no-store policies

## 25. Logging and Metrics Implementation

Middleware records one completion log per request. Domain services emit named safe events rather than free-form dumps.

Required counters/histograms:

```text
spa_api_request_count{route,status_class}
spa_api_request_latency_ms{route}
spa_booking_create_count{source,result}
spa_capacity_transaction_retry_count{operation}
spa_capacity_rejection_count{reason}
spa_pending_booking_count{age_band}
spa_guest_protection_count{control,result}
spa_outbox_event_count{type,state}
spa_notification_attempt_count{channel,result}
spa_line_webhook_count{channel,event_type,result}
```

Do not use Booking ID, phone, User ID, or Group ID as metric labels. Those values create cardinality and privacy risk.

## 26. Test Files and Required Cases

### 26.1 API Unit Tests

```text
tests/unit/test_booking_window.py
tests/unit/test_bucket_generation.py
tests/unit/test_resource_allocator.py
tests/unit/test_booking_state_machine.py
tests/unit/test_phone_normalization.py
tests/unit/test_status_tokens.py
tests/unit/test_public_projections.py
tests/unit/test_permissions.py
tests/unit/test_line_command_parser.py
tests/unit/test_catalog_seed.py
tests/unit/test_booking_line_item_pricing.py
tests/unit/test_consent_validation.py
tests/unit/test_health_retention.py
```

### 26.2 Firestore Integration Tests

```text
tests/integration/test_create_booking_transaction.py
tests/integration/test_capacity_last_unit_concurrency.py
tests/integration/test_two_pax_atomicity.py
tests/integration/test_booking_reallocation.py
tests/integration/test_capacity_release_idempotency.py
tests/integration/test_phone_guards.py
tests/integration/test_group_confirmation_race.py
tests/integration/test_outbox_reconciliation.py
tests/integration/test_admin_invitation_binding.py
tests/integration/test_customer_profile_resolution.py
tests/integration/test_customer_profile_merge.py
tests/integration/test_health_profile_snapshot.py
tests/integration/test_consent_withdrawal_workflow.py
```

The last-capacity test launches at least 20 concurrent create attempts against one remaining unit and asserts exactly one `201`, all other deterministic `409`, bucket `usedUnits` within capacity, and one active reservation.

### 26.3 Contract and Security Tests

- OpenAPI response snapshot and generated-client drift
- Public schemas recursively reject health/internal fields
- Customer templates cannot receive health fields
- Admin Group Flex contains only health boolean/indicator
- Webhook invalid signature produces no persistent business change
- Unregistered Group and missing User ID cannot confirm
- `STAFF` cannot access users, roles, security, LINE group config, or global audit
- Revoked/expired status token returns no Booking data
- Logs redact Authorization, LINE token, status token, phone, and health details
- Direct Firestore client rules deny all access
- Couple Package charges 119,000 satang once while reserving resources for two participants
- Consent purposes are separate, unchecked-by-default in UI tests, versioned, and linked to the correct participant
- Phone-only Guest data cannot auto-merge or expose a Customer Profile
- Operational alert bridge targets only the registered LINE Admin Group and rejects protected payload fields

### 26.4 Frontend E2E

- Guest service-to-result journey
- Two-participant different-duration journey
- Couple Package two-participant / charge-once journey
- Slot becomes unavailable at submit
- Restore draft after non-sensitive navigation
- Status fragment handling and removal
- Optional LINE linking with test identity stub
- Admin Pending Queue confirm/cancel
- Admin capacity edit conflict
- Therapist assignment gate before start
- `ADMIN`/`STAFF` route visibility and API denial

## 27. Requirement-to-Test Traceability

| Requirement | Minimum automated evidence |
| --- | --- |
| `BL-BKG-001`–`003` | Customer E2E and payload validation tests |
| `BL-BKG-004`–`005` | Create transaction, guard persistence, no-expiry tests |
| `BL-BKG-006`–`008` | Guest minimum fields, status token, CAPTCHA/rate/duplicate tests |
| `BL-CAP-001`–`003` | Bucket/allocation unit and concurrent transaction tests |
| `BL-ADM-001`–`003` | Webhook signature/group/race/audit tests |
| `BL-ADM-004`–`005` | Permission matrix and separate group-principal tests |
| `BL-LINE-001`–`006` | Template privacy, linking, outbox, provider failure, and LINE-only operational alert tests |
| `BL-OPS-001`–`002` | Assignment gate and absence of customer mutation endpoints |
| `BL-PAY-001` | Contract assertion that no payment fields/endpoints exist |
| `BL-PRI-001`–`003` | Projection, profile/snapshot, consent, merge, withdrawal, retention, log, task, and rules security tests |
| `BL-CAT-001` | Seed inventory, stable IDs, pricing mode, required-pax, and charge-once tests |

## 28. Implementation Sequence

1. Scaffold SPA workspace, linting, containers, and CI checks.
2. Import existing SPA secret containers into Terraform state and provision scoped test resources in `the49-487609`; do not create secret versions.
3. Provision the production named Firestore database `spa` and Cloud Run/IAM base only after implementation approval.
4. Implement shared enums, errors, request context, and named-database Firestore repositories.
5. Implement the 11-item catalog seed, branch hours, pricing modes, resources, buckets, and availability logic.
6. Implement Guest protection, consent evidence, Customer/Health Profiles, Booking snapshots, idempotency, transaction, and status tokens.
7. Implement Admin Firebase identity, invitations, permissions, Profile merge/health edits, and Booking operations.
8. Implement LINE verification, group confirmation, outbox, worker, operational-alert bridge, and templates.
9. Implement Customer Web against approved SPA-Customer-Views UX references.
10. Implement Admin Web against approved SPA-Admin-Views UX references.
11. Run concurrency, privacy, contract, E2E, load, backup/restore, and UAT gates.
12. Supply remaining production readiness inputs and promote immutable validated images.

## 29. Definition of Done for Phase 1 Implementation

- All Business Logic acceptance rules have automated or recorded UAT evidence.
- Firestore concurrency tests prove capacity cannot exceed configured units.
- Guest and LINE-linked booking flows pass on supported mobile browsers.
- Admin role enforcement passes at both UI and API layers.
- Registered LINE group confirmation is atomic and audited.
- Initial catalog contains exactly the approved 11 services; Couple Package charge-once and required-pax behavior pass.
- Health Profile edits, immutable final snapshots, verified/provisional identity rules, Profile merge, consent evidence, and withdrawal workflow pass.
- Health details are absent from public responses, LINE payloads, tasks, URLs, logs, and metrics.
- Notification enqueue gaps and retries recover without Booking rollback or duplicate state changes.
- Production configuration contains no plaintext credentials outside approved secret stores.
- Daily backup and a timed restore drill meet the documented RPO/RTO procedure.
- P95 targets pass under at least the approved 20-session load profile.
- The final Privacy Notice/Terms URLs and the proposed three-year health retention policy (or approved replacement) are explicitly approved.
- All operational alerts are verified in the registered LINE Admin Group with no alternate Phase 1 destination.
- Business Logic, HLD, TDD, LLD, OpenAPI, Terraform, and runbooks match the deployed release.

## 30. References

- [Business Logic](./BusinessLogic.md)
- [High-Level Design](./HLD.md)
- [Technical Design](./TDD.md)
- [Customer UX reference](./DESING/Side-Customer/DESIGN.md)
- [Admin UX reference](./DESING/Side-Admin/DESIGN.md)
- [Firestore transactions](https://firebase.google.com/docs/firestore/manage-data/transactions)
- [Manage multiple Firestore databases](https://firebase.google.com/docs/firestore/manage-databases)
- [Firestore TTL](https://firebase.google.com/docs/firestore/ttl)
- [Cloud Tasks retry configuration](https://cloud.google.com/tasks/docs/configuring-queues)
- [Firebase ID token verification](https://firebase.google.com/docs/auth/admin/verify-id-tokens)
- [LINE webhook processing](https://developers.line.biz/en/docs/messaging-api/receiving-messages/)
- [LINE Messaging API retry keys](https://developers.line.biz/en/reference/messaging-api/nojs/)
