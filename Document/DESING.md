# Current Design: FlowAccount Purchasing Tax Invoice Details

## Scope

This document describes the current implementation for attaching FlowAccount `Purchasing Tax Invoice Details` to a synced receipt Expense.

The system intentionally keeps the existing FlowAccount Expense workflow:

1. Verify receipt in The 49.
2. Create paid FlowAccount Expense via `/expenses/with-payment`.
3. Attach `Purchasing Tax Invoice Details` via `/expenses/{recordId}/supplier-invoice`.
4. Attach the original receipt file to the Expense document.

It does not switch the main document type to FlowAccount Purchase/Receiving Inventory.

## Main Files

Backend:

- `backend/app/services/flowaccount_service.py`
- `backend/app/api/v1/endpoints/receipts.py`
- `backend/app/models/receipt.py`
- `backend/tests/test_flowaccount_sync.py`

Frontend:

- `frontend/src/app/(dashboard)/dashboard/receipts/[id]/page.tsx`

## Backend Design

### Payload Builder

`build_supplier_invoice_payload()` builds the payload for FlowAccount supplier invoice details.

Source fields:

- `documentSerial`
  - Request value `flowaccount_supplier_invoice_serial`
  - Fallback OCR values:
    - `OCRbyGemini.document_numbers.tax_invoice_number`
    - `OCRbyGemini.document_numbers.invoice_number`
    - `OCRbyGemini.document_numbers.receipt_number`
- `contactName`
  - `seller.legal_name`
  - fallback `seller.brand_name`
  - fallback receipt merchant
- `contactBranch`
  - `seller.branch_name`
  - fallback `สำนักงานใหญ่`
- `contactTaxId`
  - normalized from `seller.tax_id`
  - required for `P.P.30`
- `documentDate`
  - receipt header date
  - fallback current date
- `taxForm`
  - currently `1` for `P.P.30`
- `vatableAmount` and `vatAmount`
  - from `OCRbyGemini.financial_summary`
  - fallback from receipt header totals and VAT
- `file`
  - optional base64 encoded receipt image/PDF
  - max 10 MB guard

### FlowAccount Calls

Current call order in `verify_receipt_and_sync_flowaccount()`:

1. Verify and save receipt locally.
2. Pre-validate supplier invoice payload with `include_file=False`.
3. Create paid Expense:

```text
POST /expenses/with-payment
```

4. Attach Purchasing Tax Invoice Details:

```text
POST /expenses/{recordId}/supplier-invoice
```

5. Attach receipt file to Expense:

```text
POST /expenses/{recordId}/attachment
```

The pre-validation step is important because it avoids creating a new FlowAccount Expense when required supplier invoice fields are missing.

### Stored Metadata

The receipt document stores the usual FlowAccount sync fields plus supplier invoice fields:

- `flowaccount_supplier_invoice_synced`
- `flowaccount_supplier_invoice_error`
- `flowaccount_supplier_invoice_id`
- `flowaccount_supplier_invoice_serial`
- `flowaccount_supplier_invoice_status`
- `flowaccount_supplier_invoice_tax_form`

The same fields are copied into the `flowaccount_syncs` history subcollection entry.

### Error Behavior

If supplier invoice pre-validation fails:

- No FlowAccount Expense is created.
- API returns `400`.
- Receipt gets `flowaccount_synced=false` and `flowaccount_sync_error`.

If Expense creation succeeds but supplier invoice attachment fails:

- Receipt remains `flowaccount_synced=true`.
- `flowaccount_supplier_invoice_synced=false`.
- `flowaccount_supplier_invoice_error` stores the FlowAccount error.
- The frontend shows the supplier invoice failure separately.

## Frontend Design

The receipt validation page now includes a `Purchasing Tax Invoice Details` section.

Fields:

- `Tax Invoice Number`
  - Pre-filled from existing FlowAccount supplier invoice serial or OCR document numbers.
  - Required only when clicking `Verify, Save & Sync to FlowAccount`.
- `Tax Form`
  - Displayed as fixed `P.P.30`.

Frontend sync validation:

- Tax invoice number must not be blank.
- Dealer tax ID must contain exactly 13 digits.
- Transfer payment requires selected bank account.

Success state:

- Shows normal FlowAccount document serial.
- Shows `Purchasing Tax Invoice Details: synced - <serial>`.

Partial failure state:

- Shows normal FlowAccount sync success.
- Shows supplier invoice error separately.

## Tests

Current focused test file:

```bash
cd backend
PYTHONPATH=. venv/bin/python tests/test_flowaccount_sync.py
```

Covered:

- Expense payload uses seller/dealer contact fields.
- Supplier invoice payload uses receipt tax details.
- Verify/save/sync creates Expense and calls supplier invoice attachment.
- Already-synced receipts require confirmation.
- Staff users cannot sync to FlowAccount.

Frontend checks:

```bash
cd frontend
npm run lint
npm run build
```

## Known Constraints

- Tax form is currently fixed to `P.P.30`.
- P.P.30 requires a 13-digit seller tax ID.
- The supplier invoice endpoint is documented in FlowAccount tutorial docs but was not present in the downloaded Swagger snapshot at implementation time.
- If the supplier invoice file cannot be downloaded or is over 10 MB, the payload still sends invoice details without the file.
- The original receipt attachment to the Expense remains separate from the supplier invoice `file` field.

## External References

- FlowAccount Supplier Invoice CRUD:
  - `https://developers.flowaccount.com/tutorial/document-api/supplier-invoice/crud`
- FlowAccount Supplier Invoice Reference:
  - `https://developers.flowaccount.com/tutorial/document-api/supplier-invoice/reference`
