# Walkthrough

## Phase 1: Backend Implementation (Complete)

### Prompt 1 ✅ - Project Structure
- Created backend structure (25 files under `backend/`)
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
- Added `get_expense_summary(branch_id, start_date, end_date)`:
- Parameterized query over `fact_transactions`
- Calculates `total_revenue`, `total_expense`, `net_profit`, `food_cost_percent`, `top_expense_category`
- Implemented analytics endpoint:
- `backend/app/api/v1/endpoints/analytics.py`
- `GET /api/v1/analytics/summary`
- Updated receipt verification flow:
- `backend/app/api/v1/endpoints/receipts.py` now calls `insert_verified_receipt` after successful verify
- Updated router:
- `backend/app/api/v1/api.py` includes `analytics.router`

### Prompt 7 ✅ - POS Integration
- Implemented POS upload endpoint:
- `backend/app/api/v1/endpoints/pos.py`
- `POST /api/v1/pos/upload` accepts `file` + `branch_id`
- Reads CSV/Excel with pandas (`read_csv` / `read_excel`)
- Normalizes columns to standard names:
- `date`, `amount`, `payment_method`
- Maps payment methods:
- `Cash` / `เงินสด` -> `CASH`
- Other values -> `TRANSFER`
- Validates input data:
- Required columns must exist
- `amount` must be numeric and positive
- Invalid file format / missing columns / invalid data -> HTTP 400
- Inserts POS rows into BigQuery `fact_transactions`:
- One row per transaction
- `type="REVENUE"`, `source="POS_FILE"`
- Updated API router:
- `backend/app/api/v1/api.py` now includes `pos.router`

### Prompt 10.1 ✅ - Branch API and Store Policy Support
- Added branches list endpoint:
- `backend/app/api/v1/endpoints/branches.py`
- `GET /api/v1/branches` returns branch list from Firestore
- Added branch listing service:
- `backend/app/services/firestore_service.py` -> `list_branches()`
- Updated API router:
- `backend/app/api/v1/api.py` includes `branches.router`
- Added default branch seeding script:
- `backend/scripts/seed_default_branches.py`
- Seeds: Coffee Shop (`COFFEE`), Restaurant (`RESTAURANT`), Steak House (`RESTAURANT`)
- Hardened Firebase Admin init for ADC:
- `backend/app/core/security.py` initializes with explicit `projectId=settings.GCP_PROJECT_ID`

## Backend Progress Summary

| Module | Files | Status |
|---|---|---|
| Project Structure | 25 files under `backend/` | ✅ |
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
| Branches API | `backend/app/api/v1/endpoints/branches.py` | ✅ |
| Branch Seeder | `backend/scripts/seed_default_branches.py` | ✅ |
| Router | `backend/app/api/v1/api.py` | ✅ |
| App Entry | `backend/app/main.py` | ✅ |

## Phase 2: Frontend Implementation (In Progress)

### Prompt 8 ✅ - Frontend Initialization
- Created base frontend module in `frontend/` using Next.js App Router + TypeScript + Tailwind
- Added project/config files:
- `frontend/package.json`
- `frontend/tsconfig.json`
- `frontend/next.config.js`
- `frontend/tailwind.config.ts`
- `frontend/postcss.config.js`
- `frontend/next-env.d.ts`
- `frontend/.env.local` (Firebase + backend URL placeholders)
- Added core libraries:
- `frontend/src/lib/firebase.ts`
- `frontend/src/lib/api.ts`
- `frontend/src/lib/utils.ts`
- Implemented axios auth interceptor in `frontend/src/lib/api.ts`
- Implemented root app layout with Inter font:
- `frontend/src/app/layout.tsx`
- Added auth provider placeholder:
- `frontend/src/components/providers/auth-provider.tsx`
- Added basic app files for bootstrapping:
- `frontend/src/app/globals.css`
- `frontend/src/app/page.tsx`

### Prompt 9 ✅ - UI Foundation and Auth
- Created reusable UI components:
- `frontend/src/components/ui/button.tsx`
- `frontend/src/components/ui/input.tsx`
- `frontend/src/components/ui/card.tsx`
- `frontend/src/components/ui/label.tsx`
- Implemented login page:
- `frontend/src/app/(auth)/login/page.tsx`
- Uses Firebase `signInWithEmailAndPassword`
- Redirects to `/dashboard` on success
- Handles common auth errors (`wrong-password`, `user-not-found`, `invalid-credential`, `invalid-email`)
- Implemented dashboard sidebar:
- `frontend/src/components/layout/sidebar.tsx`
- Links: Dashboard, Upload Receipt, POS Import, Settings
- Implemented protected dashboard layout:
- `frontend/src/app/(dashboard)/layout.tsx`
- Includes Sidebar + top bar (user profile + logout)
- Redirects unauthenticated users to `/login`

### Prompt 10 ✅ - Receipt Upload and Validation UI
- Implemented upload page:
- `frontend/src/app/(dashboard)/dashboard/upload-receipt/page.tsx`
- Added drag-and-drop file area
- Calls `POST /api/v1/receipts/upload`
- Shows loading spinner while OCR is processing
- Redirects to `/dashboard/receipts/[id]` on success
- Implemented validation page:
- `frontend/src/app/(dashboard)/dashboard/receipts/[id]/page.tsx`
- Calls `GET /api/v1/receipts/{id}`
- Split layout: left image panel, right editable form
- Editable fields: description, amount, `category_id`
- Category dropdown includes `C1-C9` and `F1-F7`
- Calls `PUT /api/v1/receipts/{id}/verify`
- Shows success toast and redirects to Dashboard
- Fixed build-safe axios header typing:
- `frontend/src/lib/api.ts`

### Prompt 10.1 ✅ - Store Dropdown UX Policy
- Upload page now loads stores from Firestore via `GET /api/v1/branches`
- Replaced Branch ID text input with single-select store dropdown
- Enforced UX policy: `1 receipt = 1 store`
- Added retry and empty-store states in upload page
- Added store lock message in validation page (receipt cannot be reassigned)

## Frontend Progress Summary

| Module | Files | Status |
|---|---|---|
| Frontend Project Setup | `frontend/package.json`, `frontend/tsconfig.json`, `frontend/next.config.js`, `frontend/tailwind.config.ts` | ✅ |
| Environment Setup | `frontend/.env.local` | ✅ |
| Firebase Client Auth | `frontend/src/lib/firebase.ts` | ✅ |
| API Client + Token Interceptor | `frontend/src/lib/api.ts` | ✅ |
| Tailwind Utility Helper | `frontend/src/lib/utils.ts` | ✅ |
| Root Layout | `frontend/src/app/layout.tsx` | ✅ |
| Auth Provider Placeholder | `frontend/src/components/providers/auth-provider.tsx` | ✅ |
| UI Components | `frontend/src/components/ui/*` | ✅ |
| Login UI | `frontend/src/app/(auth)/login/page.tsx` | ✅ |
| Dashboard Layout + Sidebar | `frontend/src/app/(dashboard)/layout.tsx`, `frontend/src/components/layout/sidebar.tsx` | ✅ |
| Receipt Upload UI | `frontend/src/app/(dashboard)/dashboard/upload-receipt/page.tsx` | ✅ |
| Receipt Validation UI | `frontend/src/app/(dashboard)/dashboard/receipts/[id]/page.tsx` | ✅ |
| Store Dropdown (Firestore) | `frontend/src/app/(dashboard)/dashboard/upload-receipt/page.tsx` | ✅ |

## Next Prompt
- Ready for Prompt 11.
