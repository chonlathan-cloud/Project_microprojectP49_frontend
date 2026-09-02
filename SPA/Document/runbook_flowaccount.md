# FlowAccount Operations Runbook

This runbook operates the customer-sale integration defined in `action_flowaccount.md`.
It does not cover the existing receipt/expense pipeline, full tax invoices, refunds, or cash
deposit settlement.

## Release order and safety gate

1. Deploy the SPA API and private Accounting Worker with sync disabled.
2. Deploy Firestore indexes and TTL policies from `infra/firestore.indexes.json`.
3. Deploy the Worker once to obtain its stable Cloud Run URL.
4. Run `infra/accounting/provision-accounting-runtime.sh` for the target environment. The script
   creates/updates the rate-limited queue, OIDC identities, least-privilege bindings, exact secret
   access, and the paused 00:15 `Asia/Bangkok` Scheduler job.
5. Configure the environment-specific company, Project, walk-in contact, Other Channel, revenue
   account, worker URL/audience, queue, and allowlisted document URL settings.
6. In Test, set `FLOWACCOUNT_SANDBOX_CONTRACT_PROVEN=true` only after Finance verifies the two
   approved documents and exact totals. Then set `FLOWACCOUNT_SYNC_ENABLED=true` and
   `ACCOUNTING_SYNC_ENABLED=true`.
7. Confirm `/health/ready` validates the authenticated company, VAT registration, walk-in contact,
   Other Channel, database/environment boundary, OIDC identities, and queue configuration.
8. Run a manual Test backlog, failure, timeout/reconciliation, and duplicate-search scenario.
9. Production remains paused until a controlled manual payment/export smoke and Finance sign-off.
   Enable the Scheduler explicitly with `ENABLE_SCHEDULER=true` and
   `FLOWACCOUNT_SANDBOX_CONTRACT_PROVEN=true`.

Never copy secret values into an environment file, command line, document, task, log, or chat. The
deploy script validates the enabled Secret Manager versions and direct runtime IAM binding without
reading the values.

## Deployment commands

Run deployments from the repository `main` branch after committing the intended changes. The API
deploy also requires the SPA worktree to be clean.

Test reads its accounting flags from `services/api/.env-test` and
`services/accounting-worker/.env-test`:

```bash
cd SPA
DEPLOY_ENVIRONMENT=test SERVICE_NAME=spa-api-test bash deploy_API.sh
DEPLOY_ENVIRONMENT=test bash deploy_Accounting_Worker.sh
```

Production must remain fail-closed while Production FlowAccount readiness is incomplete. Confirm
`ACCOUNTING_SYNC_ENABLED=false` in `services/api/.env-prod`; explicitly force the Worker flag off:

```bash
cd SPA
DEPLOY_ENVIRONMENT=prod bash deploy_API.sh
DEPLOY_ENVIRONMENT=prod FLOWACCOUNT_SYNC_ENABLED=false bash deploy_Accounting_Worker.sh
```

After Production credentials, master data, indexes/TTL, controlled smoke, and Finance sign-off pass,
turning on Production sync is a separate approved change to both Production environment files and a
new deployment. Do not enable it only through an ad-hoc shell override.

## Pause

Pause the environment's Scheduler job, pause its Cloud Tasks queue, and deploy both API and Worker
with their accounting/sync flags disabled. Do not delete queued tasks, export records, attempts, or
provider documents. Local customer-payment evidence remains authoritative and the backlog stays
recoverable.

Use this sequence for a company/contact/channel mismatch, suspected credential exposure, repeated
authorization failures, or unexplained duplicate provider results.

## Resume

Verify the exact environment and Firestore database, then restore Worker readiness first. Resume the
queue, run one selected `READY` export, verify the FlowAccount document and local IDs, and only then
resume the nightly Scheduler. A manual backlog run is bounded to 100 records; use repeated runs for a
larger backlog while watching provider rate limits.

## Credential rotation

Add a new enabled Secret Manager version to the existing environment-specific secret container.
Deploy a new Worker revision, verify readiness and one Test request, then disable the old version.
Do not grant the SPA API, Admin Web, Notification Worker, or the opposite environment access to the
FlowAccount secrets.

## Unknown outcomes and duplicate review

- `RECONCILE_REQUIRED`: do not retry create. Use Admin **Reconcile**; the worker searches the exact
  deterministic `externalDocumentId` for the accounting date.
- One exact match becomes `SYNCED` and persists provider IDs/serial.
- No exact match or multiple matches becomes `REVIEW_REQUIRED`; Finance compares FlowAccount and
  the immutable SPA payment before any correction.
- Never reset a synced export to `READY`, delete a provider document to retry, or use the cash
  deposit record as a customer sale.

## Operational checks

Review the Admin Payments & Accounting page for oldest backlog, `RETRYABLE`,
`RECONCILE_REQUIRED`, `REVIEW_REQUIRED`, run progress, and cash-settlement state. Privacy-safe
failure events go through the existing Notification Worker to the LINE Admin Group and contain only
environment, run/export references, safe error class, and Admin link.

Escalate when the oldest claimable export exceeds 26 hours, reconciliation exceeds 30 minutes, the
nightly run is absent at 01:00 Bangkok time, or provider `429`/`5xx` repeats. Logs and alerts must not
contain customer identity, phone, health data, credentials, access tokens, raw provider responses,
or financial line-item details.

Retention is enforced by Firestore TTL for attempts (90 days), run summaries (one year), and
accounting exports (seven years). Financial audit events carry a seven-year `retentionUntil` marker;
do not apply a shorter generic audit purge to those events.
