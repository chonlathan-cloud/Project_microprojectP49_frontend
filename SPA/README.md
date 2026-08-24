# SPA 49 Booking & Operations

This directory is the isolated SPA product defined by `Document/BusinessLogic.md`, `HLD.md`, `TDD.md`, and `LLD.md`. It does not import from the Receipt frontend or backend.

## Implemented Phase 1 core

- Two independent Next.js applications: mobile-first customer booking and desktop-first admin operations.
- Shared TypeScript contracts and the approved 11-service / 17-variant catalog.
- FastAPI booking transaction with 15-minute duration buckets, 1–2 pax, idempotency,
  active-pending guard, phone normalization, status links, audit/outbox and privacy-safe projections.
- Health consent evidence and separate retained health profiles with audited Admin access.
- Admin Firebase Authentication, booking transitions with optimistic versioning, closures,
  resource activation, therapist registry/assignment and no-show gate.
- Admin CRM/Campaign/Coupon workspace with masked customer lists, audited PII reveal and
  consent-filtered CSV export, versioned campaign lifecycle, and transactional redeem/void.
- Notification Worker with Cloud Tasks dispatch, Scheduler reconciliation, retry state and LINE sender.
- Unit, build, API smoke, isolated Test Cloud and responsive browser evidence.

Both web applications use the SPA API through a server-side `/api/spa/*` proxy. Admin data
requires a verified Firebase ID token and an active `app_users` record or `admin_invites` entry.
Customer catalog, availability, booking submission and secure status resolution use live API data.

## Local commands

```bash
cd SPA
npm install
npm run dev:customer
npm run dev:admin
npm run lint
npm run typecheck
npm run build
```

```bash
cd SPA/services/api
uv sync --extra dev --frozen
uv run pytest
uv run uvicorn app.main:app --reload --port 8080
```

For local Admin Web development, create `apps/admin-web/.env.local` with the API URL:

```bash
SPA_API_URL=http://localhost:8080
```

For Cloud Run Admin Web, pass the deployed API URL through the environment file accepted by `deploy_Admin_Web.sh`:

```bash
SPA_API_URL=https://spa-api-<hash>-<region>.run.app
```

The Admin Web uses an internal `/api/spa/*` server proxy, so the API URL is not exposed to browser code. The API runtime identity must have Firestore read access to `spa-db`, and `FIRESTORE_DATABASE=spa-db` must remain set on the API service.

Service cover images are stored in a private Cloud Storage bucket and streamed through the API. Review/provision it with `infra/iam/service-assets-bucket.sh` and `infra/iam/service-assets-bucket.sh --apply`, set `SERVICE_ASSETS_BUCKET` on the API, then dry-run/import the legacy covers from `services/api` with `uv run python scripts/import_service_images.py` and `uv run python scripts/import_service_images.py --apply`. Only users with the `ADMIN` application role can upload, replace, or remove a cover; `STAFF` remains read-only.

Promote approved master configuration from Test to Production with the API promotion tool. It
copies only `branches`, `services`, and `resources` by default; dry-run is mandatory before apply:

```bash
cd SPA/services/api
uv run python scripts/promote_firestore_config.py --report /tmp/spa-promotion-dry-run.json
uv run python scripts/promote_firestore_config.py \
  --apply --confirm-target spa-db --confirm-plan REVIEWED_PLAN_DIGEST \
  --report /tmp/spa-promotion-apply.json
```

Use `--include-therapists` only after verifying the records represent real staff. Special closures
require both `--include-special-closures` and an explicit `--closure-from YYYY-MM-DD`. Differing
Production documents remain conflicts unless `--allow-updates` is supplied. The tool never copies
bookings, capacity usage, health/consent data, identity records, audit events, notification state,
webhook events, or idempotency records. Firestore promotion does not copy service image objects;
validate the configured Production asset bucket separately. Apply also requires the exact digest
printed by the reviewed dry-run; any intervening source or target change invalidates approval.

Production Admin and Customer deployments require an explicit production `SPA_API_URL`; the deploy scripts reject an omitted URL or a `spa-api-test` target to prevent cross-environment routing.

Production API, Customer Web, and Notification Worker deployments default all LINE bindings to the
`spa-line-prod-*-Prod` Secret Manager resources. An overridden production secret name must either
use a production suffix (`-Prod`, `-prod`, or `-production`) or carry the Secret Manager label
`environment=prod` (or `environment=production`). Non-production deployments retain the
unsuffixed LINE secret defaults unless explicitly overridden. Both deploy preflights also require
an enabled `latest` version and a direct `roles/secretmanager.secretAccessor` grant for the runtime
service account on every bound secret.

Customer Web keeps Booking and Campaign LIFF applications independently configurable while using
the same LINE Login channel/provider for stable customer identity. `LINE_LIFF_ID` is bound from
`spa-line-customer-liff-id` for Booking; `LINE_CAMPAIGN_V1_LIFF_ID` is bound from
`spa-line-campaign-v1-liff-id` for Campaign v1. Do not replace the Booking LIFF secret when adding
or rotating a Campaign LIFF app.

Campaigns that require an active LINE friendship check `line_friendships` first. Webhook and
Followers API records are server-verified. The `welcome-50` campaign may explicitly allow a
positive LIFF `getFriendship()` result as client-attested evidence so followers who added the OA
before webhook capture can still register. The verified LINE ID token remains the customer
identity authority and coupon uniqueness key; the browser never supplies a trusted LINE user ID.
Following alone creates no CRM customer or PII record—those are created only after form submission
and privacy acknowledgement.

Set the policy on an already-seeded campaign with a dry-run followed by the confirmed write. The
policy script accepts `--project`, `--database`, `--campaign`, and the required
`--allow-liff-evidence true|false` options. For example:

```bash
cd SPA/services/api
uv run python scripts/set_campaign_friendship_policy.py \
  --database spa-test-db --campaign welcome-50 --allow-liff-evidence true
uv run python scripts/set_campaign_friendship_policy.py \
  --database spa-test-db --campaign welcome-50 --allow-liff-evidence true \
  --apply --confirm-database spa-test-db
```

For a verified or premium LINE OA, the optional backfill tool retrieves follower IDs directly from
LINE and writes only deterministic hashes to `line_friendships`. It reads both secret values through
`gcloud` without printing them and defaults to dry-run:

```bash
uv run python scripts/sync_line_followers.py --environment test
uv run python scripts/sync_line_followers.py --environment test \
  --apply --confirm-database spa-test-db

uv run python scripts/sync_line_followers.py --environment production
uv run python scripts/sync_line_followers.py --environment production \
  --apply --confirm-database spa-db
```

If LINE returns `403`, that OA does not have Followers API access; keep the explicit LIFF evidence
policy enabled for this low-value campaign instead of attempting a follower export.

The notification worker has its own lockfile and environment under `services/notification-worker`
and defaults to port `8081` locally. Test messages are prefixed `[TEST]` whenever
`APP_ENV` is not `production`.

## Cloud Run deployment

Each deployable has an independent deployment script:

```bash
./SPA/deploy_Customer_Web.sh
./SPA/deploy_Admin_Web.sh
./SPA/deploy_API.sh
./SPA/deploy_Notification_Worker.sh
```

The scripts submit the appropriate Dockerfile to Cloud Build, store the versioned image in the regional `spa` Artifact Registry repository, and deploy the image with the Cloud Run sizing and access policy from `Document/TDD.md`. Customer Web, Admin Web, and SPA API are public Cloud Run services. Notification Worker is private and uses internal ingress.

By default, Production deployments require `main`, a clean SPA worktree, and impersonate
`project-the49@the49-487609.iam.gserviceaccount.com`. Isolated Test deployment may explicitly set
`REQUIRE_CLEAN_WORKTREE=false`. Set `AUTH_MODE=none` to use the active gcloud identity, or
`AUTH_MODE=key` with `SERVICE_ACCOUNT_KEY_PATH` only for an explicitly approved local workflow.
Never commit a key or `.env` file.

Each script supports its own `SERVICE_NAME`, `IMAGE_NAME`, `ENV_FILE`, `RUNTIME_SERVICE_ACCOUNT`, sizing, and authentication overrides. The expected runtime identities are:

- `spa-customer-web-sa@${PROJECT_ID}.iam.gserviceaccount.com`
- `spa-admin-web-sa@${PROJECT_ID}.iam.gserviceaccount.com`
- `spa-api-sa@${PROJECT_ID}.iam.gserviceaccount.com`
- `spa-worker-sa@${PROJECT_ID}.iam.gserviceaccount.com`

Infrastructure currently provisioned in `the49-487609` includes `spa-test-db`, separate Test
Cloud Run services, Test/Production Cloud Tasks queues, Test Scheduler reconciliation, scoped
Worker IAM, Firestore indexes, PITR and daily backup schedules. Deployment scripts do not create
or rotate Secret Manager versions.

## Production gates

Do not promote to Production while any gate below remains open:

- LINE Admin bot must successfully push to the configured test Group ID.
- Account owner must finish Google Passkey/2-Step Verification and complete Admin UAT.
- Draft `/privacy` and `/terms` content must receive Legal/Product approval.
- LIFF/LINE customer linking, reCAPTCHA verification, automated browser suite, load test and
  backup restore drill must pass.
- SPA worktree must be committed and clean so the deployed image is traceable; Codex does not
  commit or push this work because the Product Owner reserved that Git step.
