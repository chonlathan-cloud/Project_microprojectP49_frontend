# Action Plan: Sync Verified OCR Receipts To FlowAccount

## 1. Goal

Add a FlowAccount sync action to the existing receipt validation workflow.

Current flow:

```text
Upload Receipt -> OCR/AI extracts fields -> user reviews receipt -> Verify & Save
```

New flow:

```text
Upload Receipt -> OCR/AI extracts fields -> user reviews receipt
  -> Verify & Save
  -> or Verify, Save & Sync to FlowAccount
```

The new button must create a paid FlowAccount expense document and attach the original receipt image. This feature exports verified The 49 receipt data to FlowAccount. It does not import FlowAccount expenses into The 49.

---

## 2. Product Decisions

- Use FlowAccount Client Credentials.
- Use FlowAccount sandbox first.
- Keep credentials only in backend runtime configuration.
- Add a second action button on `frontend/src/app/(dashboard)/dashboard/receipts/[id]/page.tsx` next to `Verify & Save`.
- Button label: `Verify, Save & Sync to FlowAccount`.
- The button must first run the same validation and save behavior as `Verify & Save`.
- Only after the receipt is verified should the backend create a FlowAccount paid expense document.
- Attach the original receipt image from the receipt's stored `image_url`.
- If the receipt was already synced to FlowAccount, show a confirmation modal before creating a new FlowAccount document.

---

## 3. FlowAccount API Scope

Official references:

- `https://developers.flowaccount.com/api-reference`
- `https://developers.flowaccount.com/swagger.yml`

Servers:

- Sandbox: `https://openapi.flowaccount.com/test`
- Production: `https://openapi.flowaccount.com/v1`

Required endpoints:

- `POST /token`
- Expense creation endpoint for paid expense documents: `POST /expenses/with-payment`
- Attachment endpoint for expense documents: `POST /expenses/{id}/attachment`

Implementation must verify exact request/response shapes from the Swagger spec before coding the service. Do not use FlowAccount create/edit/delete APIs beyond the paid expense creation and attachment required by this feature.

---

## 4. Backend Configuration

Update `backend/app/core/config.py` and `backend/.env.example`.

Add:

```env
FLOWACCOUNT_ENABLED=false
FLOWACCOUNT_BASE_URL=https://openapi.flowaccount.com/test
FLOWACCOUNT_CLIENT_ID=
FLOWACCOUNT_CLIENT_SECRET=
FLOWACCOUNT_SCOPE=flowaccount-api
FLOWACCOUNT_GUID=
FLOWACCOUNT_TOKEN_CACHE_SECONDS=84000
FLOWACCOUNT_TIMEOUT_SECONDS=20
FLOWACCOUNT_DEFAULT_PAYMENT_METHOD=CASH
FLOWACCOUNT_DEFAULT_PAYMENT_CHANNEL=Cash
FLOWACCOUNT_BANK_ACCOUNT_ID=0
FLOWACCOUNT_EXPENSE_SYSTEM_CODE=0
FLOWACCOUNT_EXPENSE_CATEGORY_ID=0
FLOWACCOUNT_EXPENSE_CREDIT_ID=0
FLOWACCOUNT_EXPENSE_CREDIT_CATEGORY=0
FLOWACCOUNT_EXPENSE_DEBIT_ID=0
FLOWACCOUNT_EXPENSE_DEBIT_CATEGORY=0
```

FlowAccount transfer payments require a configured FlowAccount bank account ID. Use `CASH` by default for sandbox until bank account IDs and FlowAccount expense category/account IDs are configured. Use a standard-library HTTP client or add `httpx` if preferred.

Acceptance criteria:

- App starts when FlowAccount variables are empty and `FLOWACCOUNT_ENABLED=false`.
- FlowAccount endpoints return a clear error when disabled or unconfigured.
- No FlowAccount secret is exposed to frontend responses or logs.

---

## 5. Backend Services

Create `backend/app/services/flowaccount_service.py`.

Responsibilities:

- Generate and cache access tokens.
- Create a paid FlowAccount expense from a verified receipt.
- Attach the original receipt file.
- Avoid logging secrets, tokens, full credential payloads, or raw FlowAccount error bodies.

Recommended functions:

```python
get_access_token() -> str
create_paid_expense_from_receipt(receipt: dict, branch: dict) -> dict
attach_receipt_file(flowaccount_record_id: str, receipt: dict) -> dict
```

Create `backend/app/services/flowaccount_mapping.py` if mapping grows. For Phase 1, map:

- receipt merchant/header merchant -> FlowAccount contact name
- receipt header date -> `publishedOn`
- verified receipt items -> FlowAccount item lines
- verified total -> paid expense total
- branch name -> FlowAccount `projectName`
- configured/default payment method -> FlowAccount payment method
- configured FlowAccount accounting category IDs -> required expense item accounting fields

Use verified receipt data only. Do not sync draft OCR output.

---

## 6. Receipt Sync State

Extend receipt Firestore documents with FlowAccount metadata.

Suggested fields:

```json
{
  "flowaccount_synced": true,
  "flowaccount_synced_at": "2026-06-29T10:00:00Z",
  "flowaccount_synced_by": "firebase_uid",
  "flowaccount_record_id": "123",
  "flowaccount_document_id": "456",
  "flowaccount_document_serial": "EXP2026060001",
  "flowaccount_attachment_synced": true,
  "flowaccount_sync_error": null,
  "flowaccount_sync_count": 1
}
```

If the user confirms re-sync, create a new FlowAccount document and increment `flowaccount_sync_count`. Preserve the latest FlowAccount IDs on the receipt and optionally append history under:

```text
receipts/{receipt_id}/flowaccount_syncs/{auto_id}
```

Each history record should include user ID, timestamp, FlowAccount IDs, attachment status, and error summary.

---

## 7. Backend API

Create `backend/app/api/v1/endpoints/flowaccount.py` and register it in `backend/app/api/v1/api.py`.

### `GET /api/v1/flowaccount/status`

Purpose:

- Show whether FlowAccount sync is enabled and configured.
- Optionally test token generation.

Access:

- `admin`
- `executive`

Do not return credentials or access tokens.

### `POST /api/v1/receipts/{receipt_id}/verify-and-sync-flowaccount`

Purpose:

- Validate the same payload as `PUT /api/v1/receipts/{receipt_id}/verify`.
- Save the receipt as verified.
- Insert verified rows into BigQuery using the existing OCR flow.
- Create a paid FlowAccount expense.
- Attach the original receipt image.
- Save sync metadata back to the receipt.

Request:

```json
{
  "items": [
    {"description": "Milk", "amount": 95.0, "category_id": "C1"}
  ],
  "adjustments": [],
  "total_check": 95.0,
  "confirm_resync": false
}
```

Response:

```json
{
  "receipt_id": "receipt_123",
  "status": "VERIFIED",
  "bigquery_rows_inserted": 2,
  "flowaccount_synced": true,
  "flowaccount_record_id": "123",
  "flowaccount_document_serial": "EXP2026060001",
  "flowaccount_attachment_synced": true
}
```

Validation:

- Block staff users unless product owner later approves staff sync.
- Block sync when FlowAccount is disabled or unconfigured.
- Block draft/unverified payloads with invalid category, total, or item data.
- If receipt already has `flowaccount_synced=true` and `confirm_resync=false`, return a 409 response requiring confirmation.
- If FlowAccount creation succeeds but attachment fails, keep the FlowAccount document metadata and store `flowaccount_attachment_synced=false` plus a readable error.

---

## 8. Frontend UX

Update `frontend/src/app/(dashboard)/dashboard/receipts/[id]/page.tsx`.

Current action:

- `Verify & Save`

Add second action:

- `Verify, Save & Sync to FlowAccount`

Button behavior:

1. Reuse the same client-side validation as `Verify & Save`.
2. Call `POST /api/v1/receipts/{receipt_id}/verify-and-sync-flowaccount`.
3. Disable both buttons while saving/syncing.
4. Show progress text such as `Saving and syncing...`.
5. Show success message with FlowAccount document serial.
6. If backend returns 409 already-synced conflict, show a confirmation modal:
   - Title: `Create another FlowAccount document?`
   - Explain that this receipt has already been synced.
   - Actions: `Cancel` and `Create New FlowAccount Document`
7. After success, keep the user on the receipt detail page or offer:
   - `Upload Another Receipt`
   - `View Transactions`

Do not place FlowAccount secrets or credential status details in frontend environment variables.

---

## 9. Data Mapping

### Receipt To FlowAccount Expense

| The 49 Receipt | FlowAccount |
|---|---|
| `receipt.id` | internal reference/note |
| `receipt.header.merchant` | contact/vendor name |
| `receipt.header.date` | `publishedOn` |
| branch name | `projectName` |
| verified line item description | expense item name/description |
| verified line item amount | item total |
| receipt adjustments | discount/adjustment handling if supported; otherwise include as explicit line items |
| `total_check` | paid total |
| default payment method | payment method/channel |
| `image_url` file bytes | attachment |

If FlowAccount requires contact IDs rather than free-text contact names, add a contact lookup/create decision before implementation. Do not create contacts automatically unless confirmed.

---

## 10. Error Handling

Expected errors:

- FlowAccount disabled.
- Missing client ID or client secret.
- Token request failed.
- Paid expense creation failed.
- Attachment upload failed.
- Receipt image missing or inaccessible.
- Receipt already synced and requires confirmation.
- BigQuery insert failed.
- Firestore sync metadata update failed.

Error rules:

- Keep receipt verification and FlowAccount sync states explicit.
- Do not hide partial success. If BigQuery saved but FlowAccount failed, tell the user.
- Do not expose FlowAccount access token, client secret, or raw sensitive response bodies.

---

## 11. Testing Plan

Backend tests:

- FlowAccount disabled returns clear error.
- Missing credentials returns clear error.
- Token success and token cache reuse.
- Token failure does not expose secret.
- Verified receipt maps to paid expense payload.
- Receipt image attachment uses stored `image_url`.
- Already-synced receipt returns 409 without confirmation.
- Confirmed re-sync creates a new FlowAccount document.
- Attachment failure stores partial sync metadata.
- Staff role is blocked if admin/executive-only policy is used.

Frontend manual QA:

- Upload receipt still works.
- OCR auto-fills receipt fields.
- `Verify & Save` still works without FlowAccount.
- `Verify, Save & Sync to FlowAccount` validates fields before calling backend.
- Already-synced confirmation modal appears.
- Success message shows FlowAccount document serial.
- Mobile layout shows both buttons without overlap.

Sandbox verification:

1. Use FlowAccount sandbox URL and sandbox credentials.
2. Upload a test receipt.
3. Review and correct OCR fields.
4. Click `Verify, Save & Sync to FlowAccount`.
5. Confirm paid expense exists in FlowAccount sandbox.
6. Confirm receipt image is attached.
7. Confirm The 49 BigQuery transaction rows still use `source = "OCR"`.

---

## 12. Implementation Order

1. Add FlowAccount backend config and an HTTP client.
2. Add FlowAccount token client.
3. Verify exact Swagger payload for paid expense creation and attachment.
4. Add receipt-to-FlowAccount payload mapper.
5. Add attachment download/upload handling from receipt `image_url`.
6. Add receipt sync metadata helpers in `firestore_service.py`.
7. Add `verify-and-sync-flowaccount` backend endpoint.
8. Add already-synced 409 confirmation behavior.
9. Add frontend button and modal on receipt validation page.
10. Add backend mocked tests.
11. Run existing receipt tests.
12. Run sandbox end-to-end verification.

---

## 13. Acceptance Criteria

- User uploads a receipt and OCR/AI auto-fills fields.
- User can still click `Verify & Save` without FlowAccount.
- User can click `Verify, Save & Sync to FlowAccount`.
- Sync only happens after the receipt data passes verification.
- Backend creates a paid FlowAccount expense document.
- Backend attaches the original receipt image.
- Existing BigQuery OCR transaction flow remains unchanged.
- Already-synced receipts require explicit confirmation before creating another FlowAccount document.
- Sync metadata is stored on the receipt.
- No FlowAccount credentials or tokens are exposed to the browser or logs.
