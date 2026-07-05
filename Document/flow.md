# Flow: Receipt Sync With Purchasing Tax Invoice Details

## Goal

Use The 49 receipt validation screen to verify a receipt, create a paid Expense document in FlowAccount, and attach the FlowAccount `Purchasing Tax Invoice Details` section to that Expense.

This flow does not create a FlowAccount Purchase document. It keeps the existing Expense sync and adds the purchasing tax invoice detail section after the Expense is created.

## Prerequisites

- User must be logged in as `admin` or `executive`.
- Backend `.env` must have FlowAccount enabled and configured.
- FlowAccount should be tested with sandbox first:
  - `FLOWACCOUNT_ENABLED=true`
  - `FLOWACCOUNT_BASE_URL=https://openapi.flowaccount.com/test`
  - `FLOWACCOUNT_CLIENT_ID`
  - `FLOWACCOUNT_CLIENT_SECRET`
  - `FLOWACCOUNT_GUID` if required by the credential
  - Expense account/category config IDs
  - Bank account ID if transfer payment is used
- Receipt must have seller/dealer tax ID with 13 digits.
- Receipt must have a tax invoice number. If OCR does not extract it, the user must enter it manually.

## Local Startup

Backend:

```bash
cd backend
source venv/bin/activate
uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm run dev
```

Open:

```text
http://localhost:3000/dashboard/upload-receipt
```

## User Flow

1. Login as an `admin` or `executive` user.
2. Go to `Dashboard > Upload Receipt`.
3. Select the store/branch.
4. Upload the receipt image or PDF.
5. Open the generated receipt validation page.
6. Review line items, categories, adjustments, and total check.
7. Review `Dealer Details`:
   - Dealer Name
   - Tax ID, exactly 13 digits
   - Branch, usually `สำนักงานใหญ่`
   - Optional contact fields
8. Review `Purchasing Tax Invoice Details`:
   - Tax Invoice Number is required.
   - Tax Form is currently fixed to `P.P.30`.
9. Review `FlowAccount Payment`:
   - Choose `Transfer` or `Cash`.
   - If `Transfer`, select the bank account.
10. Click `Verify, Save & Sync to FlowAccount`.

## Expected Result In The App

On success, the receipt page should show:

```text
Synced to FlowAccount
Document: <FlowAccount expense serial> - Attachment: synced
Purchasing Tax Invoice Details: synced - <tax invoice number>
```

If the Expense sync succeeds but the Purchasing Tax Invoice Details attach fails, the app still records the Expense sync and shows the supplier invoice error separately.

## Expected Result In FlowAccount

In FlowAccount sandbox:

1. Open the created Expense document.
2. Confirm the normal Expense/payment details exist.
3. Confirm the `Purchasing Tax Invoice Details` section is populated.
4. Confirm the original receipt file is attached.

## Regression Commands

Backend mocked FlowAccount tests:

```bash
cd backend
PYTHONPATH=. venv/bin/python tests/test_flowaccount_sync.py
```

Frontend validation:

```bash
cd frontend
npm run lint
npm run build
```

## Troubleshooting

`Purchasing tax invoice number is required before syncing to FlowAccount.`

- Enter the tax invoice number in `Purchasing Tax Invoice Details`.

`Dealer tax ID must contain 13 digits for purchasing tax invoice sync.`

- Fix the dealer tax ID in `Dealer Details`.

`Please select a transfer bank account before syncing to FlowAccount.`

- Select a FlowAccount bank account, or switch payment method to `Cash`.

`Receipt already synced to FlowAccount. Confirm before creating another FlowAccount document.`

- The receipt already has a FlowAccount sync record. Confirm only if a duplicate FlowAccount document is intended.
