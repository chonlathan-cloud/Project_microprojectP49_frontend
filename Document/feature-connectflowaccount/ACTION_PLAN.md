# Action Plan: Connect FlowAccount Paid Expense Documents

## 1. Goal

Implement a FlowAccount integration for The 49 Smart P&L system that imports only FlowAccount expense documents with paid status into the existing analytics transaction flow.

The feature must:

- Use FlowAccount Client Credentials.
- Read paid expense documents from FlowAccount sandbox/production API.
- Map FlowAccount `projectName` to an internal branch.
- Auto-categorize expense line items from item text using the same categorization logic as OCR receipts.
- Detect duplicates before import.
- Show a popup/modal to the user when duplicates are found.
- Let the user decide whether to skip existing records or import duplicate records.
- Insert accepted records into BigQuery `fact_transactions` with `source = "FLOWACCOUNT"`.

Do not replace the existing OCR receipt flow. FlowAccount is a new expense source alongside `OCR` and `POS_FILE`.

---

## 2. Current Repo Context

### Backend

Current backend stack:

- FastAPI
- Pydantic
- Google Cloud SDK
- Firestore
- BigQuery
- Firebase auth

Important existing files:

- `backend/app/core/config.py`
- `backend/app/api/v1/api.py`
- `backend/app/api/v1/endpoints/transactions.py`
- `backend/app/services/bigquery_service.py`
- `backend/app/services/firestore_service.py`
- `backend/app/services/categorization.py`
- `backend/app/models/branch.py`
- `backend/.env`
- `backend/.env.example`

Current transaction table:

- BigQuery table: `fact_transactions`
- Used by dashboard, transactions page, and AI insight.
- Existing sources: `OCR`, `POS_FILE`.
- New source required: `FLOWACCOUNT`.

### Frontend

Current frontend stack:

- Next.js App Router
- TypeScript
- Tailwind
- Axios
- Firebase auth

Important existing files:

- `frontend/src/app/(dashboard)/dashboard/settings/page.tsx`
- `frontend/src/app/(dashboard)/transactions/page.tsx`
- `frontend/src/components/TransactionTable.tsx`
- `frontend/src/lib/api.ts`
- `frontend/src/types/transaction.ts`

Current Settings page is a placeholder, so it is the right place to add FlowAccount connection and sync controls.

---

## 3. External API Facts Confirmed

Official FlowAccount API reference:

- `https://developers.flowaccount.com/api-reference#tag/expenses/get/expenses`
- Scalar spec source: `https://developers.flowaccount.com/swagger.yml`

FlowAccount servers:

- Sandbox: `https://openapi.flowaccount.com/test`
- Production: `https://openapi.flowaccount.com/v1`

Authentication:

- Endpoint: `POST /token`
- Content-Type: `application/x-www-form-urlencoded`
- Request fields:
  - `grant_type`
  - `scope`
  - `client_id`
  - `client_secret`
  - `guid` optional if credential works without it
- Confirmed sandbox token response:
  - HTTP 200
  - `token_type = Bearer`
  - `expires_in = 86400`
  - `access_token` exists

Expense list:

- Endpoint: `GET /expenses`
- Query fields:
  - `currentPage`
  - `pageSize`
  - `searchString`
  - `range`
  - `month`
  - `year`
  - `startDate`
  - `endDate`
- Header:
  - `Authorization: Bearer <access_token>`

Paid status:

- Sample response confirmed:
  - `statusString = "paid"`
  - `status = "5"`
- Implementation should treat a document as paid when:
  - `str(statusString).lower() == "paid"`, or
  - `str(status) == "5"`

Important expense fields:

- `recordId`
- `documentId`
- `documentSerial`
- `publishedOn`
- `projectName`
- `reference`
- `contactName`
- `items`
- `grandTotal`
- `payments.paymentDate`
- `payments.paymentMethod`
- `payments.paymentChannel`
- `status`
- `statusString`

---

## 4. Product Decisions

### 4.1 Auth Model

Use FlowAccount Client Credentials.

Credentials must live only in backend runtime configuration. They must not be stored in frontend env variables or sent to the browser.

### 4.2 Branch Mapping

Use FlowAccount `projectName` as the primary branch mapping key.

Recommended branch schema extension:

```json
{
  "id": "branch_001",
  "name": "Siam Square One",
  "type": "COFFEE",
  "flowaccount_project_names": ["Siam Square One", "SSO"]
}
```

Mapping rules:

1. Normalize `projectName` by trimming whitespace and lowercasing.
2. Compare against every branch's `flowaccount_project_names`.
3. If exactly one branch matches, use that branch.
4. If no branch matches, mark the document as `UNMAPPED_BRANCH`.
5. If multiple branches match, mark the document as `AMBIGUOUS_BRANCH`.
6. The user must resolve unmapped or ambiguous documents in the Settings sync preview before import.
7. When a user manually maps a `projectName` to a branch, save that mapping to the branch document for future syncs.

Do not infer branch from contact/vendor name as the main strategy. Vendor names are reused across branches and will create wrong P&L data.

### 4.3 Category Mapping

Auto-categorize from FlowAccount item text using the existing OCR categorization logic.

Input text priority for each item:

1. `item.description`
2. `item.nameLocal`
3. `item.nameForeign`
4. FlowAccount document `remarks`
5. FlowAccount document `contactName`
6. fallback: `documentSerial`

Use branch type to select categories:

- `COFFEE` -> `C1-C9`
- `RESTAURANT` -> `F1-F7`

Implementation should reuse:

- `backend/app/services/categorization.py`
- `backend/app/models/branch.py`

### 4.4 Duplicate Handling

The system must not silently skip or silently duplicate records.

The sync flow must have two steps:

1. Preview
2. Import confirmation

If duplicates are detected during preview, the frontend must show a popup/modal to the user and ask for a decision:

- `Skip existing`
- `Import duplicate`

No import should happen until the user explicitly chooses.

---

## 5. Backend Implementation Plan

### Phase 1: Configuration

Update `backend/app/core/config.py`.

Add settings:

- `FLOWACCOUNT_ENABLED`
- `FLOWACCOUNT_BASE_URL`
- `FLOWACCOUNT_CLIENT_ID`
- `FLOWACCOUNT_CLIENT_SECRET`
- `FLOWACCOUNT_SCOPE`
- `FLOWACCOUNT_GUID`
- `FLOWACCOUNT_TOKEN_CACHE_SECONDS`
- `FLOWACCOUNT_TIMEOUT_SECONDS`
- `FLOWACCOUNT_PAGE_SIZE`
- `FLOWACCOUNT_SYNC_LOOKBACK_DAYS`
- `FLOWACCOUNT_DEFAULT_PAYMENT_METHOD`

Suggested defaults:

```env
FLOWACCOUNT_ENABLED=false
FLOWACCOUNT_BASE_URL=https://openapi.flowaccount.com/test
FLOWACCOUNT_CLIENT_ID=
FLOWACCOUNT_CLIENT_SECRET=
FLOWACCOUNT_SCOPE=flowaccount-api
FLOWACCOUNT_GUID=
FLOWACCOUNT_TOKEN_CACHE_SECONDS=84000
FLOWACCOUNT_TIMEOUT_SECONDS=20
FLOWACCOUNT_PAGE_SIZE=50
FLOWACCOUNT_SYNC_LOOKBACK_DAYS=30
FLOWACCOUNT_DEFAULT_PAYMENT_METHOD=TRANSFER
```

Update `backend/.env.example`.

Do not add real credentials to `.env.example`.

Acceptance criteria:

- App can start if FlowAccount env vars are empty and `FLOWACCOUNT_ENABLED=false`.
- App returns a clear error if FlowAccount endpoints are called while required env vars are missing.
- No FlowAccount secret is referenced from frontend code.

---

### Phase 2: FlowAccount API Client Service

Create `backend/app/services/flowaccount_service.py`.

Responsibilities:

- Generate access token.
- Cache token until near expiry.
- Call `GET /expenses`.
- Handle pagination.
- Filter paid documents.
- Normalize documents into internal preview records.
- Avoid logging secrets or access tokens.

Token function:

```python
get_access_token() -> str
```

Behavior:

- POST to `{FLOWACCOUNT_BASE_URL}/token`.
- Use `application/x-www-form-urlencoded`.
- Send:
  - `grant_type=client_credentials`
  - `scope`
  - `client_id`
  - `client_secret`
  - `guid` only if configured.
- Cache `access_token`.
- Refresh token when now is greater than `expires_at - 300 seconds`.

Expense fetch function:

```python
list_expenses(start_date: str, end_date: str, page_size: int | None = None) -> list[dict]
```

Behavior:

- GET `/expenses`.
- Use `currentPage`, `pageSize`, `range=5`, `startDate`, `endDate`.
- Continue pages until:
  - returned list is empty, or
  - page count reaches total document count, or
  - returned rows are fewer than page size.
- Filter paid documents with:
  - `statusString.lower() == "paid"` or
  - `status == "5"`.

Recommended defensive parsing:

- Convert all unknown numeric values with safe helpers.
- Treat missing `items` as empty list.
- Treat missing `payments` as `{}`.
- Treat missing `publishedOn` as invalid for import and require review.

Acceptance criteria:

- Unit tests can mock token response and expense pages.
- Service returns only paid documents.
- Service does not expose token or secret in logs, response, exceptions, or test snapshots.

---

### Phase 3: Firestore Sync State

Add sync state functions to `backend/app/services/firestore_service.py`.

Recommended collections:

#### `flowaccount_imports`

Document ID:

```text
flowaccount_expense_{recordId}
```

Fields:

```json
{
  "id": "flowaccount_expense_123",
  "record_id": "123",
  "document_id": "456",
  "document_serial": "EXP2026060001",
  "status": "paid",
  "branch_id": "branch_001",
  "source": "FLOWACCOUNT",
  "imported_at": "2026-06-29T10:00:00Z",
  "imported_by_user_id": "firebase_uid",
  "bigquery_rows_inserted": 3,
  "duplicate_policy": "skip_existing",
  "raw_snapshot": {
    "projectName": "Siam Square One",
    "publishedOn": "2026-06-28",
    "grandTotal": 1000.0
  }
}
```

#### `flowaccount_sync_runs`

Document ID:

```text
auto-generated
```

Fields:

```json
{
  "id": "sync_run_id",
  "started_at": "2026-06-29T10:00:00Z",
  "finished_at": "2026-06-29T10:00:10Z",
  "started_by_user_id": "firebase_uid",
  "start_date": "2026-06-01",
  "end_date": "2026-06-29",
  "status": "SUCCESS",
  "documents_seen": 10,
  "paid_documents": 7,
  "ready_to_import": 5,
  "duplicate_documents": 1,
  "unmapped_documents": 1,
  "rows_inserted": 12,
  "error": null
}
```

Required helper functions:

- `get_flowaccount_import(record_id: str) -> dict | None`
- `create_flowaccount_import(data: dict) -> dict`
- `list_flowaccount_imports_by_record_ids(record_ids: list[str]) -> dict[str, dict]`
- `create_flowaccount_sync_run(data: dict) -> dict`
- `update_flowaccount_sync_run(run_id: str, fields: dict) -> dict`
- `update_branch_flowaccount_mapping(branch_id: str, project_name: str) -> dict`

Acceptance criteria:

- A previously imported `recordId` can be detected quickly.
- Sync runs are auditable.
- Manual branch mapping can be reused in future syncs.

---

### Phase 4: BigQuery Insert Support

Update `backend/app/services/bigquery_service.py`.

Add:

```python
insert_flowaccount_expenses(rows: list[dict]) -> int
```

Internal BigQuery row shape:

```json
{
  "transaction_id": "flowaccount_expense_{recordId}_item_{index}",
  "branch_id": "branch_001",
  "date": "2026-06-28",
  "type": "EXPENSE",
  "category_id": "F1",
  "category_name": "Main Ingredients (วัตถุดิบหลัก)",
  "item_name": "หมูบด",
  "amount": 500.0,
  "payment_method": "TRANSFER",
  "source": "FLOWACCOUNT",
  "uploaded_by_user_id": "",
  "verified_by_user_id": "firebase_uid",
  "created_at": "2026-06-29T10:00:00Z"
}
```

Transaction ID strategy:

- Normal import:
  - `flowaccount_expense_{recordId}_item_{index}`
- Import duplicate:
  - `flowaccount_expense_{recordId}_duplicate_{syncRunId}_item_{index}`

This is required because BigQuery streaming inserts do not act as upserts.

Payment method mapping:

- FlowAccount `paymentMethod == 1` -> `CASH`
- FlowAccount `paymentMethod == 5` -> `TRANSFER`
- FlowAccount `paymentChannel` contains `cash` or `เงินสด` -> `CASH`
- FlowAccount `paymentChannel` contains `transfer` or `โอน` -> `TRANSFER`
- Otherwise use `FLOWACCOUNT_DEFAULT_PAYMENT_METHOD`

Date mapping:

Use:

1. `payments.paymentDate` if present
2. else `publishedOn`

Reason:

- P&L cash basis usually wants actual payment date for paid expenses.
- If FlowAccount payment date is missing, `publishedOn` is the safest fallback.

Line item mapping:

- If `items` exists and has valid positive `total`, insert one row per item.
- If `items` is empty or invalid, insert one fallback row using `grandTotal`.
- Ignore items with zero or negative amount unless product owner wants refund/credit handling later.

Acceptance criteria:

- Dashboard totals include FlowAccount expenses automatically.
- Transactions page can filter `source=FLOWACCOUNT`.
- No duplicate rows are inserted unless user chooses `Import duplicate`.

---

### Phase 5: Branch Mapping Resolver

Add branch mapping logic in a backend service, either:

- `backend/app/services/flowaccount_mapping.py`, or
- inside `flowaccount_service.py` if small.

Recommended function:

```python
resolve_branch_for_project(project_name: str, branches: list[dict]) -> dict
```

Return shape:

```json
{
  "status": "MATCHED",
  "branch_id": "branch_001",
  "branch_name": "Siam Square One",
  "reason": null
}
```

Possible statuses:

- `MATCHED`
- `UNMAPPED_BRANCH`
- `AMBIGUOUS_BRANCH`

Matching details:

- Normalize both source `projectName` and branch aliases.
- Exact match first.
- Optional later enhancement: fuzzy match, but do not include fuzzy match in Phase 1 import because it can create wrong accounting data.

Acceptance criteria:

- Documents with known `projectName` are auto-mapped.
- Documents without mapping are blocked from import and shown in UI for user action.
- User can save a new mapping.

---

### Phase 6: Duplicate Detection

Implement duplicate detection during preview.

Duplicate types:

#### Exact duplicate

Same FlowAccount `recordId` already exists in `flowaccount_imports`.

Result:

```json
{
  "duplicate_type": "EXACT_FLOWACCOUNT_RECORD",
  "severity": "high",
  "existing_import_id": "flowaccount_expense_123"
}
```

#### Possible duplicate

A similar transaction already exists from OCR or another source.

Check against BigQuery `fact_transactions`.

Recommended matching criteria:

- Same branch
- Same date or within 1 day
- Same amount or amount difference <= 1 baht
- Type is `EXPENSE`
- Source is `OCR` or `FLOWACCOUNT`
- Optional text similarity using normalized `item_name`, merchant/contact, or document reference

Result:

```json
{
  "duplicate_type": "POSSIBLE_SAME_EXPENSE",
  "severity": "medium",
  "matched_transactions": [...]
}
```

Backend preview should group duplicates by FlowAccount document, not by line item, so the popup is understandable to users.

Acceptance criteria:

- Exact duplicate is always detected before import.
- Possible duplicate is shown as warning, not hard block.
- User decision is required before duplicate import.

---

### Phase 7: Backend API Endpoints

Create `backend/app/api/v1/endpoints/flowaccount.py`.

Add router:

```python
router = APIRouter(prefix="/flowaccount", tags=["FlowAccount"])
```

Register it in:

- `backend/app/api/v1/api.py`

#### 7.1 `GET /api/v1/flowaccount/status`

Purpose:

- Check whether FlowAccount is configured and token can be generated.

Access:

- `admin`
- `executive`

Response:

```json
{
  "enabled": true,
  "configured": true,
  "base_url": "https://openapi.flowaccount.com/test",
  "token_ok": true,
  "environment": "sandbox",
  "last_sync": {
    "started_at": "2026-06-29T10:00:00Z",
    "status": "SUCCESS",
    "rows_inserted": 12
  }
}
```

Do not return:

- `client_id`
- `client_secret`
- `access_token`
- raw auth response

#### 7.2 `POST /api/v1/flowaccount/preview`

Purpose:

- Fetch paid FlowAccount expenses for a date range.
- Resolve branches.
- Categorize items.
- Detect duplicates.
- Return a preview for user confirmation.

Request:

```json
{
  "start_date": "2026-06-01",
  "end_date": "2026-06-29"
}
```

Response:

```json
{
  "preview_id": "sync_run_id",
  "start_date": "2026-06-01",
  "end_date": "2026-06-29",
  "summary": {
    "documents_seen": 10,
    "paid_documents": 7,
    "ready_to_import": 5,
    "duplicates": 1,
    "unmapped": 1,
    "blocked": 1
  },
  "documents": [
    {
      "flowaccount_record_id": "123",
      "document_serial": "EXP2026060001",
      "status": "paid",
      "published_on": "2026-06-28",
      "payment_date": "2026-06-29",
      "project_name": "Siam Square One",
      "branch_status": "MATCHED",
      "branch_id": "branch_001",
      "contact_name": "masked-or-safe-name",
      "grand_total": 1000.0,
      "items_count": 3,
      "duplicate_status": "NONE",
      "import_status": "READY",
      "lines": [
        {
          "description": "หมูบด",
          "amount": 500.0,
          "category_id": "F1",
          "category_name": "Main Ingredients (วัตถุดิบหลัก)"
        }
      ]
    }
  ]
}
```

Import statuses:

- `READY`
- `DUPLICATE_REQUIRES_DECISION`
- `UNMAPPED_BRANCH_REQUIRES_DECISION`
- `INVALID_DOCUMENT`

#### 7.3 `POST /api/v1/flowaccount/import`

Purpose:

- Import documents from a preview result.
- Respect duplicate decisions and branch mappings.

Request:

```json
{
  "preview_id": "sync_run_id",
  "duplicate_policy": "skip_existing",
  "documents": [
    {
      "flowaccount_record_id": "123",
      "action": "import",
      "branch_id": "branch_001"
    },
    {
      "flowaccount_record_id": "456",
      "action": "skip"
    }
  ],
  "save_branch_mappings": true
}
```

Allowed duplicate policies:

- `skip_existing`
- `import_duplicate`

Allowed document actions:

- `import`
- `skip`

Response:

```json
{
  "status": "success",
  "preview_id": "sync_run_id",
  "documents_imported": 4,
  "documents_skipped": 2,
  "rows_inserted": 12,
  "duplicate_policy": "skip_existing"
}
```

Validation:

- Block import if preview is missing or expired.
- Block import if any selected document still has unresolved branch mapping.
- Block exact duplicates unless policy is `import_duplicate`.
- Block non-admin/non-executive users.

#### 7.4 Optional `GET /api/v1/flowaccount/sync-runs`

Purpose:

- Show sync history in Settings.

Response:

```json
{
  "sync_runs": [...]
}
```

---

## 6. Frontend Implementation Plan

### Phase 1: Transaction Source Support

Update:

- `frontend/src/app/(dashboard)/transactions/page.tsx`
- `frontend/src/types/transaction.ts` if source type becomes stricter later

Changes:

- Add `FLOWACCOUNT` to `normalizeSource`.
- Add `FLOWACCOUNT` option in Source dropdown.

Acceptance criteria:

- User can filter transaction table by `FLOWACCOUNT`.
- URL query `?source=FLOWACCOUNT` remains stable after refresh.

---

### Phase 2: Settings Page FlowAccount Panel

Update:

- `frontend/src/app/(dashboard)/dashboard/settings/page.tsx`

Build a real Settings surface with a FlowAccount section.

UI controls:

- Connection status indicator
- Date range inputs
- `Preview Paid Expenses` button
- Preview summary
- Document preview table
- Branch mapping dropdown for unmapped documents
- Duplicate warning modal
- Final `Import` button
- Last sync result

Use existing UI components:

- `Button`
- `Input`
- `Label`
- `Card`

Use lucide icons where useful:

- `RefreshCcw`
- `AlertTriangle`
- `CheckCircle`
- `Plug`
- `GitBranch`

Do not show FlowAccount secrets.

### Phase 3: Preview UX

When user clicks `Preview Paid Expenses`:

1. Call `POST /api/v1/flowaccount/preview`.
2. Show summary:
   - Paid documents
   - Ready to import
   - Duplicates
   - Unmapped
   - Estimated BigQuery rows
3. Show table:
   - Document serial
   - Date
   - Payment date
   - Project name
   - Branch
   - Contact
   - Amount
   - Status
   - Duplicate state

For unmapped branch:

- Show a branch dropdown on the row.
- Require branch selection before import.
- If `save_branch_mappings` is checked, persist mapping after import.

### Phase 4: Duplicate Popup

When preview response contains duplicates:

Show modal before import:

Title:

```text
Duplicate expenses found
```

Content:

- Explain that these FlowAccount expenses may already exist in The 49.
- Show duplicate count.
- Show each duplicate document with:
  - FlowAccount document serial
  - FlowAccount amount
  - Existing transaction source
  - Existing transaction date
  - Existing amount
  - Existing item/contact text if available

Actions:

- `Skip existing`
- `Import duplicate`
- `Cancel`

Behavior:

- `Skip existing`: send `duplicate_policy = "skip_existing"`.
- `Import duplicate`: send `duplicate_policy = "import_duplicate"`.
- `Cancel`: do not import.

Acceptance criteria:

- Duplicate import never happens without explicit user selection.
- Modal is keyboard accessible.
- Modal text fits on mobile and desktop.

### Phase 5: Import UX

When user confirms import:

1. Call `POST /api/v1/flowaccount/import`.
2. Disable buttons while importing.
3. Show result:
   - documents imported
   - documents skipped
   - rows inserted
4. Offer link/button to Transactions page filtered by `source=FLOWACCOUNT`.

Acceptance criteria:

- User sees clear success/failure result.
- Errors from backend are shown in a readable alert.
- User can immediately verify imported data in Transactions page.

---

## 7. Data Mapping Details

### FlowAccount Document To Internal Document

| FlowAccount | Internal |
|---|---|
| `recordId` | `flowaccount_record_id` |
| `documentId` | `flowaccount_document_id` |
| `documentSerial` | `document_serial` |
| `statusString` | `flowaccount_status` |
| `publishedOn` | fallback transaction date |
| `payments.paymentDate` | preferred transaction date |
| `projectName` | branch mapping key |
| `contactName` | vendor/merchant display |
| `items` | transaction lines |
| `grandTotal` | fallback amount |

### FlowAccount Item To Transaction Line

| FlowAccount Item | BigQuery `fact_transactions` |
|---|---|
| `description` / `nameLocal` / `nameForeign` | `item_name` |
| `total` | `amount` |
| auto-categorized result | `category_id`, `category_name` |
| mapped branch | `branch_id` |
| payment method mapping | `payment_method` |
| `"FLOWACCOUNT"` | `source` |

### BigQuery Row Example

```json
{
  "transaction_id": "flowaccount_expense_200271145_item_1",
  "branch_id": "branch_001",
  "date": "2026-06-29",
  "type": "EXPENSE",
  "category_id": "F1",
  "category_name": "Main Ingredients (วัตถุดิบหลัก)",
  "item_name": "หมูบด",
  "amount": 500.0,
  "payment_method": "TRANSFER",
  "source": "FLOWACCOUNT",
  "uploaded_by_user_id": "",
  "verified_by_user_id": "firebase_uid",
  "created_at": "2026-06-29T10:00:00Z"
}
```

---

## 8. Permissions And Security

Only these roles should use FlowAccount sync:

- `admin`
- `executive`

Staff users should not see or run FlowAccount sync.

Security rules:

- Never return FlowAccount secrets.
- Never log access token.
- Never put `FLOWACCOUNT_CLIENT_SECRET` in frontend env.
- Backend errors should mention "FlowAccount token request failed" but not include response bodies if they might contain sensitive values.
- Sync preview should avoid returning unnecessary raw FlowAccount payloads to frontend.

---

## 9. Error Handling

### Expected errors

- FlowAccount disabled.
- Missing client id or client secret.
- Token request failed.
- FlowAccount API timeout.
- Expense API returned non-200.
- Invalid date range.
- No paid documents in date range.
- Unmapped branch.
- Duplicate found.
- BigQuery insert failed.
- Firestore sync state write failed.

### Error response format

Use FastAPI `HTTPException` with readable `detail`.

Examples:

```json
{
  "detail": "FlowAccount is not configured."
}
```

```json
{
  "detail": "Some FlowAccount documents are missing branch mapping."
}
```

```json
{
  "detail": "Duplicate FlowAccount records require user decision before import."
}
```

---

## 10. Testing Plan

### Backend unit tests

Add tests for:

- Token generation success.
- Token cache reuse.
- Token failure.
- Expense pagination.
- Paid filter using `statusString == "paid"`.
- Paid filter using `status == "5"`.
- Non-paid documents excluded.
- Branch mapping by `projectName`.
- Unmapped branch.
- Ambiguous branch.
- Category mapping from item description.
- Fallback row when no valid items.
- Payment method mapping.
- Exact duplicate detection.
- Possible duplicate detection.
- Import with `skip_existing`.
- Import with `import_duplicate`.
- Permission blocks staff user.

### Frontend tests/manual QA

Manual QA checklist:

- Settings page shows FlowAccount status.
- Preview works for date range with paid expenses.
- Empty date range result is readable.
- Unmapped branch blocks import until user selects branch.
- Duplicate popup appears.
- `Skip existing` does not insert duplicate.
- `Import duplicate` inserts duplicate with unique transaction id.
- Transactions page can filter `FLOWACCOUNT`.
- Dashboard totals include FlowAccount expenses.
- Mobile layout does not overlap text.

### Sandbox integration test

Use sandbox credentials only.

Test flow:

1. Generate token.
2. Call `/expenses`.
3. Confirm paid documents are filtered correctly.
4. Run preview endpoint.
5. Run import into test branch and test BigQuery dataset if available.
6. Verify `fact_transactions` rows.

Do not run sandbox integration test in normal CI unless credentials are available.

---

## 11. Rollout Plan

### Step 1: Local development

- Add config.
- Add backend services.
- Add endpoints.
- Add frontend Settings UI.
- Add transaction source filter.
- Run unit tests.

### Step 2: Sandbox verification

- Use FlowAccount sandbox URL.
- Preview recent paid expenses.
- Verify branch mapping from `projectName`.
- Verify category mapping.
- Verify duplicate modal.
- Import a small date range.
- Check BigQuery `fact_transactions`.
- Check dashboard totals.

### Step 3: Production preparation

- Add production credentials to backend runtime env or Secret Manager.
- Confirm production base URL:
  - `https://openapi.flowaccount.com/v1`
- Set `FLOWACCOUNT_ENABLED=true`.
- Confirm branch `flowaccount_project_names` are configured.
- Run preview before first production import.

### Step 4: Production first import

- Start with a narrow date range, e.g. 1 day.
- Use preview.
- Resolve unmapped projects.
- Skip duplicates unless intentionally importing duplicates.
- Validate transactions and dashboard.

### Step 5: Operating process

Recommended Phase 1 operation:

- Manual sync from Settings page.
- Admin/executive chooses date range.
- User reviews preview and duplicate popup.
- User imports.

Future enhancement:

- Scheduled daily sync using Cloud Scheduler.
- Still keep duplicate review queue for uncertain duplicates.

---

## 12. Implementation Order

Recommended order for developer:

1. Add backend FlowAccount config.
2. Add `flowaccount_service.py`.
3. Add Firestore sync state helpers.
4. Add branch mapping resolver.
5. Add BigQuery insert helper for FlowAccount rows.
6. Add duplicate detection query/helper.
7. Add `/flowaccount/status`.
8. Add `/flowaccount/preview`.
9. Add `/flowaccount/import`.
10. Register FlowAccount router.
11. Update backend transaction allowed sources to include `FLOWACCOUNT`.
12. Update frontend transaction source filter.
13. Replace Settings placeholder with FlowAccount sync UI.
14. Add duplicate popup modal.
15. Add tests.
16. Run sandbox verification.

---

## 13. Acceptance Criteria

Feature is complete when:

- Admin/executive can open Settings and see FlowAccount connection status.
- Admin/executive can preview paid FlowAccount expenses by date range.
- Only paid documents are included.
- `projectName` maps to internal branch.
- Unmapped `projectName` requires user branch selection.
- Item text is auto-categorized into the correct branch category set.
- Duplicate documents trigger a popup before import.
- User can choose `Skip existing` or `Import duplicate`.
- Imported rows appear in BigQuery `fact_transactions`.
- Imported rows use `source = "FLOWACCOUNT"`.
- Transactions page can filter by `FLOWACCOUNT`.
- Dashboard totals include FlowAccount expenses.
- No credentials or tokens are exposed to frontend or logs.

---

## 14. Open Questions For Product Owner

These are not blockers for Phase 1, but should be decided later:

1. Should FlowAccount expenses use `paymentDate` or `publishedOn` for P&L reporting if both exist?
   - Recommendation: use `paymentDate` for paid expenses.
2. Should duplicate imports be allowed for exact same FlowAccount `recordId`, or only for possible OCR duplicates?
   - Recommendation: allow only after explicit `Import duplicate` modal confirmation.
3. Should branch mapping be managed only through Settings, or also through a dedicated Branch Settings page?
   - Recommendation: start in Settings, move to Branch Settings later if mappings grow.
4. Should auto sync be scheduled after manual sync is stable?
   - Recommendation: yes, but not in Phase 1.

---

## 15. Notes For Future Developer

- Keep this feature read-only against FlowAccount for Phase 1.
- Do not call FlowAccount endpoints that create, edit, pay, or delete documents.
- Do not use FlowAccount SDK as a hard dependency unless there is a strong reason. A small service wrapper is easier to test and matches this repo's current style.
- Keep the integration idempotent by default.
- Treat `Import duplicate` as an explicit user override, not normal behavior.
- Store enough import metadata to audit where each BigQuery row came from.
