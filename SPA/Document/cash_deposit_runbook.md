# Admin Cash Deposit Runbook

## Safety boundary

This workflow moves cash already recorded as customer-sale revenue into the merchant account. It must never create a second `accounting_exports` record or customer-sale notification.

Test may use Beam Playground. Production must keep `CASH_DEPOSIT_ENABLED=false` until Beam/UOB supplies written confirmation that merchant self-funding through a merchant-owned Beam PromptPay charge is permitted. Record the approval owner, date, merchant ID, limitations, and provider ticket before setting both:

```text
CASH_DEPOSIT_PROVIDER_CONTRACT_CONFIRMED=true
CASH_DEPOSIT_ENABLED=true
```

## One-time Test infrastructure

Review the dry run, then provision the private evidence bucket:

```bash
ENVIRONMENT=test SPA/infra/iam/cash-evidence-bucket.sh
ENVIRONMENT=test APPLY=true SPA/infra/iam/cash-evidence-bucket.sh
```

Deploy Firestore indexes from `SPA/infra/firestore.indexes.json`. The API runtime identity needs bucket-scoped `roles/storage.objectAdmin` and self-scoped `roles/iam.serviceAccountTokenCreator` for V4 signed URLs. Public access prevention and uniform bucket-level access remain enabled.

The provision script intentionally does not set a GCS lifecycle or retention lock. Finance must approve the evidence-retention period before Production; configure and verify that policy as a separate, reviewed infrastructure change before enabling the workflow.

## Test deployment

The checked local `.env-test` configuration enables the workflow and points its return URL to Admin Test. Deploy API and Admin Web from a traceable `main` commit. Verify `/health/ready` reports `cashDepositConfiguration=ready` before testing.

## Acceptance flow

1. Record at least one completed Booking as cash. Confirm its payment is `PAID/CASH/UNSETTLED` and its existing accounting export remains `CUSTOMER_SALE`.
2. In Admin → Payments & Accounting, choose **Deposit cash**.
3. Select one to 100 `UNSETTLED` payments and enter the physically counted amount. The total must match every satang.
4. Upload JPEG, PNG, HEIC, or HEIF evidence no larger than 10 MB. Confirm GCS generation, SHA-256, media metadata, and magic-byte validation.
5. Confirm the review dialog and create the 30-minute Beam PromptPay QR.
6. Complete the Playground charge. Verify webhook or manual reconciliation changes the batch to `COMPLETED` and every allocation to `SETTLED`.
7. Verify no additional `accounting_exports` document was created.

The Beam QR image is returned only by the create-attempt response for the active Admin session. It is never persisted in Firestore or GCS. If the drawer is reopened, reconcile the existing attempt; do not create a duplicate charge merely to recover the image.

## Failure handling

- `CREATE_UNKNOWN` / batch `REVIEW`: reconcile by stable `SPA-CASH-DEP-*` reference before any retry.
- `FAILED` or `EXPIRED`: allocations stay `DEPOSIT_PENDING`; reconcile, then create a new attempt.
- Amount, merchant, currency, reference, or transaction-window mismatch: batch and allocations move to `REVIEW`; do not manually mark settled.
- A draft may be cancelled only before an attempt exists. Cancellation releases all allocation guards and returns payments to `UNSETTLED`.
- Evidence objects stay private. Admin receives short-lived object-specific signed URLs only after role and branch checks.

## Production activation checklist

- Written Beam/UOB merchant self-funding approval is attached to the operational change record.
- Production evidence bucket and IAM are provisioned separately from Test.
- Finance-approved evidence lifecycle/retention is configured and tested on the Production bucket.
- Production Beam webhook is registered for `charge.succeeded` and `charge.failed`.
- A low-value controlled Production transaction is approved by Finance and observed end to end.
- Alerts cover webhook failures, `REVIEW`, stale `QR_ACTIVE`, and stale `DEPOSIT_PENDING` states.
- Rollback is `CASH_DEPOSIT_ENABLED=false`; existing active attempts must still be reconciled before operational closure.
