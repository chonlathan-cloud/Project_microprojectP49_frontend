# SPA 49 Booking & Operations

This directory is the isolated SPA product defined by `Document/BusinessLogic.md`, `HLD.md`, `TDD.md`, and `LLD.md`. It does not import from the Receipt frontend or backend.

## Implemented foundation

- Two independent Next.js applications: mobile-first customer booking and desktop-first admin operations.
- Shared TypeScript contracts and the approved 11-service / 17-variant catalog.
- FastAPI domain foundation for catalog, availability, pricing, state transitions, and privacy-safe public projections.
- Notification Worker health and privacy-safe template foundation.
- Unit tests for the business-critical pure domain rules.

The browser applications currently use explicitly labelled local preview data. Booking writes, Firebase Admin authentication, Firestore transactions, LINE delivery, reCAPTCHA verification, and cloud infrastructure are not simulated as successful production actions.

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

The notification worker has its own lockfile and environment under `services/notification-worker` and defaults to port `8081` locally.

## Cloud Run deployment

Each deployable has an independent deployment script:

```bash
./SPA/deploy_Customer_Web.sh
./SPA/deploy_Admin_Web.sh
./SPA/deploy_API.sh
./SPA/deploy_Notification_Worker.sh
```

The scripts submit the appropriate Dockerfile to Cloud Build, store the versioned image in the regional `spa` Artifact Registry repository, and deploy the image with the Cloud Run sizing and access policy from `Document/TDD.md`. Customer Web, Admin Web, and SPA API are public Cloud Run services. Notification Worker is private and uses internal ingress.

By default, deployments require the `main` branch and impersonate `project-the49@the49-487609.iam.gserviceaccount.com`, matching the repository's existing receipt deployment scripts. Set `AUTH_MODE=none` to use the active gcloud identity, or `AUTH_MODE=key` with `SERVICE_ACCOUNT_KEY_PATH` only for an explicitly approved local workflow. Never commit a key or `.env` file.

Each script supports its own `SERVICE_NAME`, `IMAGE_NAME`, `ENV_FILE`, `RUNTIME_SERVICE_ACCOUNT`, sizing, and authentication overrides. The expected runtime identities are:

- `spa-customer-web-sa@${PROJECT_ID}.iam.gserviceaccount.com`
- `spa-admin-web-sa@${PROJECT_ID}.iam.gserviceaccount.com`
- `spa-api-sa@${PROJECT_ID}.iam.gserviceaccount.com`
- `spa-worker-sa@${PROJECT_ID}.iam.gserviceaccount.com`

The deployment scripts create the shared Artifact Registry repository when it is absent. They do not create service accounts, grant IAM roles, create Firestore/Tasks/Scheduler resources, add secret versions, or bypass the production-readiness gates below. Those resources must be provisioned before the corresponding production service is deployed.

## Production gates

Do not provision or deploy production resources until the remaining inputs in TDD section 33 are supplied. In particular, the health-retention proposal is not approved merely because the implementation exposes its configuration flag.
