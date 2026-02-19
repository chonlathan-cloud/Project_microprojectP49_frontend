# Walkthrough

## Phase 1: Backend Implementation (Complete)

### Prompt 1 ✅ - Project Structure
- Created backend structure (25+ files under `backend/`)
- Key files: `backend/requirements.txt`, `backend/Dockerfile`

### Prompt 2 ✅ - Core Config and Models
- Implemented `backend/app/core/config.py`
- Implemented models:
- `backend/app/models/receipt.py`
- `backend/app/models/branch.py`

### Prompt 3 ✅ - Infrastructure Services
- Implemented:
- `backend/app/core/security.py`
- `backend/app/services/firestore_service.py`
- `backend/app/services/ocr_service.py`

### Prompt 4 ✅ - Intelligence Services
- Implemented:
- `backend/app/services/ai_service.py`
- `backend/app/services/categorization.py`

### Prompt 5 ✅ - API Endpoints and App Entry
- Implemented:
- `backend/app/api/v1/endpoints/receipts.py`
- `backend/app/api/v1/api.py`
- `backend/app/main.py`

### Prompt 6 ✅ - BigQuery and Analytics
- Implemented `backend/app/services/bigquery_service.py`
- Added `insert_verified_receipt(receipt)`:
- Transforms verified receipt items to `fact_transactions`
- Inserts rows via `bq_client.insert_rows_json`
- Uses `type="EXPENSE"` for receipt rows
- Implemented analytics endpoint:
- `backend/app/api/v1/endpoints/analytics.py`
- `GET /api/v1/analytics/summary`

### Prompt 7 ✅ - POS Integration
- Implemented POS upload endpoint:
- `backend/app/api/v1/endpoints/pos.py`
- `POST /api/v1/pos/upload` accepts `file` + `branch_id`
- Reads CSV/Excel with pandas (`read_csv` / `read_excel`)
- Normalizes columns to `date`, `amount`, `payment_method`
- Maps payment methods:
- `Cash` / `เงินสด` -> `CASH`
- Other values -> `TRANSFER`
- Validation:
- Required columns must exist
- `amount` must be numeric and positive
- Invalid file format / missing columns / invalid data -> HTTP 400
- Inserts POS rows into BigQuery:
- `type="REVENUE"`, `source="POS_FILE"`

### Prompt 10.1 ✅ - Branch API and Store Policy Support
- Added branches endpoint:
- `backend/app/api/v1/endpoints/branches.py`
- `GET /api/v1/branches`
- Added service:
- `backend/app/services/firestore_service.py` -> `list_branches()`
- Added default branch seeding script:
- `backend/scripts/seed_default_branches.py`
- Seeds:
- Coffee Shop (`COFFEE`)
- Restaurant (`RESTAURANT`)
- Steak House (`RESTAURANT`)
- Hardened Firebase Admin init for ADC with explicit `projectId`

### Prompt 10.2 ✅ - Receipt Preview via Signed URL
- Backend now generates signed URL for receipt image preview
- Endpoint:
- `GET /api/v1/receipts/{id}` returns `image_preview_url`
- Signed URL expiry configured to 30 minutes (1800s)

### Prompt 11 ✅ - Analytics Filter Hardening
- `GET /api/v1/analytics/summary` now supports optional `category_id`
- Added input validation:
- Date format (`YYYY-MM-DD`)
- `start_date <= end_date`
- `branch_id` exists
- `category_id` must match branch type
- `COFFEE -> C1-C9`
- `RESTAURANT -> F1-F7`
- Updated BigQuery query with parameterized category filter
- Revenue remains included; expense can be narrowed by category

### Prompt 12 ✅ - AI Insight RAG (BigQuery + Playbook Embeddings)
- Added AI endpoint for dashboard insight:
- `backend/app/api/v1/endpoints/ai.py`
- `POST /api/v1/ai/chat`
- AI chat now combines:
- BigQuery summary data
- Knowledge Base retrieval from playbook embeddings
- Added response metadata:
- `citations`
- `kb_used`
- `fallback_mode` (`hybrid` / `bigquery_only`)
- Added fallback policy:
- If KB unavailable, continue with BigQuery-only response (no hard fail)
- Added knowledge base service:
- `backend/app/services/knowledge_base.py`
- Loads `backend/app/data/business_playbook.json`
- Uses Vertex embeddings (`text-embedding-004`) + Chroma vector store
- Auto-init on app startup (configurable)
- Cloud Run-friendly persist dir default: `/tmp/the49_chroma`
- Updated AI service for insight generation:
- `backend/app/services/ai_service.py`
- Uses dedicated insight model config (`VERTEX_AI_INSIGHT_MODEL`)
- Thai-first answer policy with English numbers/technical terms
- Supports in-answer reference style from playbook snippets
- Expanded business playbook v1:
- `backend/app/data/business_playbook.json`
- Increased from 3 to 27 entries
- Covers `General`, `C1-C9`, `F1-F7`
- Added KB dependencies:
- `langchain`
- `langchain-community`
- `langchain-google-vertexai`
- `chromadb`

### Backend Data Model Update ✅ - Audit Columns in BigQuery
- `fact_transactions` now expects:
- `uploaded_by_user_id STRING NULLABLE`
- `verified_by_user_id STRING NULLABLE`
- Used by both receipt verify flow and POS upload flow

## Backend Progress Summary

| Module | Files | Status |
|---|---|---|
| Project Structure | `backend/` | ✅ |
| Core Config | `backend/app/core/config.py` | ✅ |
| Pydantic Models | `backend/app/models/receipt.py`, `backend/app/models/branch.py` | ✅ |
| Security | `backend/app/core/security.py` | ✅ |
| Firestore CRUD | `backend/app/services/firestore_service.py` | ✅ |
| OCR / Document AI | `backend/app/services/ocr_service.py` | ✅ |
| AI / Vertex AI | `backend/app/services/ai_service.py` | ✅ |
| Categorization | `backend/app/services/categorization.py` | ✅ |
| Receipts API | `backend/app/api/v1/endpoints/receipts.py` | ✅ |
| POS Endpoint | `backend/app/api/v1/endpoints/pos.py` | ✅ |
| Analytics API | `backend/app/api/v1/endpoints/analytics.py` | ✅ |
| AI Chat API | `backend/app/api/v1/endpoints/ai.py` | ✅ |
| Branches API | `backend/app/api/v1/endpoints/branches.py` | ✅ |
| Branch Seeder | `backend/scripts/seed_default_branches.py` | ✅ |
| Knowledge Base (RAG) | `backend/app/services/knowledge_base.py` | ✅ |
| Playbook Data | `backend/app/data/business_playbook.json` | ✅ |
| Router | `backend/app/api/v1/api.py` | ✅ |
| App Entry | `backend/app/main.py` | ✅ |

## BigQuery Schema (Current)

`fact_transactions`:

- `transaction_id STRING REQUIRED`
- `branch_id STRING REQUIRED`
- `date DATE REQUIRED`
- `type STRING REQUIRED` (`EXPENSE` / `REVENUE`)
- `category_id STRING NULLABLE`
- `category_name STRING NULLABLE`
- `item_name STRING NULLABLE`
- `amount NUMERIC REQUIRED`
- `payment_method STRING NULLABLE`
- `source STRING REQUIRED` (`OCR` / `POS_FILE`)
- `uploaded_by_user_id STRING NULLABLE`
- `verified_by_user_id STRING NULLABLE`
- `created_at TIMESTAMP REQUIRED`

## Phase 2: Frontend Implementation (In Progress)

### Prompt 8 ✅ - Frontend Initialization
- Created frontend module in `frontend/` with:
- Next.js App Router
- TypeScript
- Tailwind CSS
- Axios
- Firebase Client SDK
- Core files:
- `frontend/package.json`
- `frontend/tsconfig.json`
- `frontend/next.config.js`
- `frontend/tailwind.config.ts`
- `frontend/.env.local`
- Core libs:
- `frontend/src/lib/firebase.ts`
- `frontend/src/lib/api.ts`
- `frontend/src/lib/utils.ts`

### Prompt 9 ✅ - UI Foundation and Auth
- Reusable UI components:
- `frontend/src/components/ui/button.tsx`
- `frontend/src/components/ui/input.tsx`
- `frontend/src/components/ui/card.tsx`
- `frontend/src/components/ui/label.tsx`
- Implemented login page:
- `frontend/src/app/(auth)/login/page.tsx`
- Implemented protected dashboard layout + sidebar:
- `frontend/src/app/(dashboard)/layout.tsx`
- `frontend/src/components/layout/sidebar.tsx`

### Prompt 9.1 ✅ - Signup + User Profile
- Added signup page:
- `frontend/src/app/(auth)/signup/page.tsx`
- Public signup enabled
- Stores profile in Firestore `users/{uid}`:
- `display_name`
- `email`
- `role` (default `staff`)
- `default_branch_id`
- `created_at`
- Post-signup behavior:
- auto-login + redirect to `/dashboard/upload-receipt`
- Updated auth provider:
- fetches profile from Firestore
- exposes `displayName` (fallback email)
- Top bar now displays `display_name` first

### Prompt 10 ✅ - Receipt Upload and Validation UI
- Upload page:
- `frontend/src/app/(dashboard)/dashboard/upload-receipt/page.tsx`
- Drag-and-drop upload
- Calls `POST /api/v1/receipts/upload`
- OCR loading state
- Redirect to `/dashboard/receipts/[id]`
- Validation page:
- `frontend/src/app/(dashboard)/dashboard/receipts/[id]/page.tsx`
- Calls `GET /api/v1/receipts/{id}`
- Editable items (description, amount, category)
- Verify + save via `PUT /api/v1/receipts/{id}/verify`

### Prompt 10.1 ✅ - Store Dropdown UX Policy
- Upload page loads stores from `GET /api/v1/branches`
- Replaced branch text input with dropdown
- Enforced policy: `1 receipt = 1 store`
- Added retry and empty-store states
- Validation page shows store lock message (cannot reassign receipt)

### Prompt 11 ✅ - Executive Dashboard and Filters
- Implemented dashboard:
- `frontend/src/app/(dashboard)/dashboard/page.tsx`
- Added:
- Date range filter (default this month)
- Summary cards (Revenue / Expense / Net Profit)
- Expense composition pie chart (`recharts`)
- Trend chart (summary bar chart)
- AI Insight box (`POST /api/v1/ai/chat`)
- Added category filter dropdown bound to selected branch type:
- `COFFEE -> C1-C9`
- `RESTAURANT -> F1-F7`
- Added role-based branch behavior:
- `admin` / `executive`: choose any branch
- `staff`: branch locked to `default_branch_id`
- AI Insight panel now renders backend citations when available
- Supports `kb_used` and `fallback_mode` response handling

## Frontend Progress Summary

| Module | Files | Status |
|---|---|---|
| Frontend Setup | `frontend/package.json`, `frontend/tsconfig.json`, `frontend/next.config.js`, `frontend/tailwind.config.ts` | ✅ |
| Env Setup | `frontend/.env.local` | ✅ |
| Firebase Auth + Firestore Client | `frontend/src/lib/firebase.ts` | ✅ |
| API Client + Token Interceptor | `frontend/src/lib/api.ts` | ✅ |
| Utility Helper | `frontend/src/lib/utils.ts` | ✅ |
| Root Layout | `frontend/src/app/layout.tsx` | ✅ |
| Auth Provider | `frontend/src/components/providers/auth-provider.tsx` | ✅ |
| UI Components | `frontend/src/components/ui/*` | ✅ |
| Login | `frontend/src/app/(auth)/login/page.tsx` | ✅ |
| Signup | `frontend/src/app/(auth)/signup/page.tsx` | ✅ |
| Dashboard Layout + Sidebar | `frontend/src/app/(dashboard)/layout.tsx`, `frontend/src/components/layout/sidebar.tsx` | ✅ |
| Receipt Upload | `frontend/src/app/(dashboard)/dashboard/upload-receipt/page.tsx` | ✅ |
| Receipt Validation | `frontend/src/app/(dashboard)/dashboard/receipts/[id]/page.tsx` | ✅ |
| Executive Dashboard | `frontend/src/app/(dashboard)/dashboard/page.tsx` | ✅ |

## Next Prompt
- Ready for next feature prompt (Phase 2 continuation).
