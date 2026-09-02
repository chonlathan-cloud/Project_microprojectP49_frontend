# FlowAccount Sandbox contract proof — 2026-09-01

This record contains non-secret Test/Sandbox bootstrap evidence for the SPA 49
customer-sale integration. Credentials and access tokens remain in Secret Manager
and are intentionally omitted.

## Resolved Sandbox configuration

| Setting | Verified value |
| --- | --- |
| API base URL | `https://openapi.flowaccount.com/test` |
| Authenticated company | `บริษัท มณี แอนด์ ซัน จำกัด sandbox` |
| VAT registration | FlowAccount company type `10` |
| Project | `Spa 49` via `projectName` |
| Walk-in contact | ID `1180474`, code `SPA49-WALKIN`, name `ลูกค้าทั่วไป - SPA 49`, individual group `1` |
| Beam/UOB Other Channel | ID `1860`, name `Beam/UOB Gateway - SPA 49`, Online Payment Gateway type `3` |
| SPA service revenue account | `41210` (`รายได้จากการให้บริการ`) |

## UAT candidate documents

| Scenario | Document | External document ID | Expected result |
| --- | --- | --- | --- |
| Beam service-only | `CA2026090001` / document `963890` | `SPATST-20260901-SVC001` | THB 350.00, VAT-inclusive VAT THB 22.90, method `13`, Other Channel `1860`, one service line |
| Customer cash service + tip | `CA2026090003` / document `963893` | `SPATST-20260901-TIP002` | THB 400.00, VAT-inclusive VAT THB 26.17, method `1`, no Other Channel, service THB 350.00 plus `SPA-TIP` THB 50.00 |

Both candidates persist Project `Spa 49`, Walk-in contact `SPA49-WALKIN`, and sell
account `41210`. The tip candidate persists the provider-visible trace
`SPA-TIP | Tip for BK-CONTRACT-TIP002` in the item description.

## Observed provider behavior

- Cash Invoice list responses use `data.totalDocument` as a decimal string, not
  `data.total` as an integer. The adapter accepts and validates this Sandbox shape.
- The Simple Cash Invoice operation accepts but does not persist the request item
  `sku` field. The integration therefore keeps service SKU in the persisted item
  description and uses `SPA-TIP | ...` as the tip trace fallback.
- `projectName = Spa 49` is accepted and returned. No `projectId` is required for
  the selected Simple document schema.
- Payment fields are returned under the `payments` object and numeric identifiers
  and amounts are serialized as strings.
- FlowAccount accepts duplicate `externalDocumentId` values. Two intentional
  duplicate-test documents, `CA2026090004` and `CA2026090005`, were created for
  `SPATST-20260901-DUP001`. Therefore `externalDocumentId` is not an idempotency
  key. Runtime safety depends on the local lease, preflight lookup, and
  unknown-outcome reconciliation; automatic blind create retry remains forbidden.

## Non-UAT Sandbox artifacts

- `CA2026090002` was created before the provider-visible `SPA-TIP` description
  fallback was added. Do not use it for accountant approval.
- `CA2026090004` and `CA2026090005` are intentional duplicate-behavior evidence.
  They are not customer-sale UAT samples.

## Release gate

As verified on 2026-09-02, the Test API has `ACCOUNTING_SYNC_ENABLED=true` and the
Test Accounting Worker has `FLOWACCOUNT_SYNC_ENABLED=true` plus
`FLOWACCOUNT_SANDBOX_CONTRACT_PROVEN=true`. The Test Scheduler remains `PAUSED` at
`15 0 * * *` in `Asia/Bangkok`; enabling continuous nightly operation remains an
explicit release action.

The historical-payment Test run synchronized 61 one-payment-per-document exports:
one authorized non-fixture historical cash payment plus 60 positive-value
`HISTORICAL_RECORD` Test fixtures. The completed nightly run processed and synced
all 60 selected fixture exports with zero failed or review results. Two zero-value
fixtures were correctly ineligible for export, and one cancelled/excluded fixture
was not exported. This is runtime integration evidence, not a substitute for formal
Finance/accountant UAT sign-off.

Automated regression validation on 2026-09-02 also passed:

- SPA API payment/accounting selection: 44 tests, including same-day distinct exports,
  replay idempotency, immutable FlowAccount contract metadata, routes, historical
  backfill, Firestore transaction helpers, reconciliation, and payment routes.
- Accounting Worker: 21 tests covering payload/client behavior, delivery and
  reconciliation outcomes, Firestore transaction helpers, and health/readiness.
- Ruff passed for both tested service scopes. The only warning was the existing
  Starlette `TestClient`/`httpx` deprecation warning.

Production remains disabled until its credentials, company identity, Project,
contact, payment channel, revenue account, Firestore indexes/TTL, controlled smoke,
and Finance sign-off pass independently. Sandbox IDs must never be reused in
Production.
