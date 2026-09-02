#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-the49-487609}"
REGION="${REGION:-asia-southeast1}"
DEPLOY_ENVIRONMENT="${DEPLOY_ENVIRONMENT:-test}"
WORKER_URL="${WORKER_URL:-}"
ENABLE_SCHEDULER="${ENABLE_SCHEDULER:-false}"
API_SERVICE_ACCOUNT="${API_SERVICE_ACCOUNT:-spa-api-sa@${PROJECT_ID}.iam.gserviceaccount.com}"

case "$DEPLOY_ENVIRONMENT" in
  test)
    QUEUE_NAME="${QUEUE_NAME:-spa-flowaccount-sync-test}"
    WORKER_SERVICE="${WORKER_SERVICE:-spa-accounting-worker-test}"
    WORKER_SERVICE_ACCOUNT="${WORKER_SERVICE_ACCOUNT:-spa-accounting-worker-test-sa@${PROJECT_ID}.iam.gserviceaccount.com}"
    TASKS_INVOKER_ID="${TASKS_INVOKER_ID:-spa-acct-tasks-test-sa}"
    SCHEDULER_INVOKER_ID="${SCHEDULER_INVOKER_ID:-spa-acct-scheduler-test-sa}"
    SCHEDULER_JOB="${SCHEDULER_JOB:-spa-flowaccount-nightly-test}"
    MAX_DISPATCHES_PER_SECOND="0.1666667"
    MAX_CONCURRENT_DISPATCHES="1"
    ;;
  prod)
    QUEUE_NAME="${QUEUE_NAME:-spa-flowaccount-sync}"
    WORKER_SERVICE="${WORKER_SERVICE:-spa-accounting-worker}"
    WORKER_SERVICE_ACCOUNT="${WORKER_SERVICE_ACCOUNT:-spa-accounting-worker-sa@${PROJECT_ID}.iam.gserviceaccount.com}"
    TASKS_INVOKER_ID="${TASKS_INVOKER_ID:-spa-acct-tasks-sa}"
    SCHEDULER_INVOKER_ID="${SCHEDULER_INVOKER_ID:-spa-acct-scheduler-sa}"
    SCHEDULER_JOB="${SCHEDULER_JOB:-spa-flowaccount-nightly}"
    MAX_DISPATCHES_PER_SECOND="1"
    MAX_CONCURRENT_DISPATCHES="2"
    ;;
  *)
    echo "ERROR: DEPLOY_ENVIRONMENT must be test or prod."
    exit 1
    ;;
esac

if [[ -z "$WORKER_URL" || "$WORKER_URL" != https://* ]]; then
  echo "ERROR: WORKER_URL must be the deployed private Accounting Worker HTTPS URL."
  exit 1
fi
if [[ "$ENABLE_SCHEDULER" != "true" && "$ENABLE_SCHEDULER" != "false" ]]; then
  echo "ERROR: ENABLE_SCHEDULER must be true or false."
  exit 1
fi
if [[ "$DEPLOY_ENVIRONMENT" == "prod" && "$ENABLE_SCHEDULER" == "true" && "${FLOWACCOUNT_SANDBOX_CONTRACT_PROVEN:-false}" != "true" ]]; then
  echo "ERROR: Refusing to enable the Production scheduler before Sandbox contract proof."
  exit 1
fi

for command in gcloud; do
  command -v "$command" >/dev/null 2>&1 || { echo "ERROR: '$command' is required."; exit 1; }
done

TASKS_INVOKER_SERVICE_ACCOUNT="${TASKS_INVOKER_ID}@${PROJECT_ID}.iam.gserviceaccount.com"
SCHEDULER_INVOKER_SERVICE_ACCOUNT="${SCHEDULER_INVOKER_ID}@${PROJECT_ID}.iam.gserviceaccount.com"
WORKER_SERVICE_ACCOUNT_ID="${WORKER_SERVICE_ACCOUNT%%@*}"

gcloud services enable cloudtasks.googleapis.com cloudscheduler.googleapis.com run.googleapis.com secretmanager.googleapis.com --project "$PROJECT_ID" --quiet

ensure_service_account() {
  local account_id="$1"
  local display_name="$2"
  if ! gcloud iam service-accounts describe "${account_id}@${PROJECT_ID}.iam.gserviceaccount.com" --project "$PROJECT_ID" >/dev/null 2>&1; then
    gcloud iam service-accounts create "$account_id" --project "$PROJECT_ID" --display-name "$display_name" --quiet
  fi
}

ensure_service_account "$TASKS_INVOKER_ID" "SPA Accounting Tasks invoker (${DEPLOY_ENVIRONMENT})"
ensure_service_account "$SCHEDULER_INVOKER_ID" "SPA Accounting Scheduler invoker (${DEPLOY_ENVIRONMENT})"
ensure_service_account "$WORKER_SERVICE_ACCOUNT_ID" "SPA Accounting Worker (${DEPLOY_ENVIRONMENT})"

if gcloud tasks queues describe "$QUEUE_NAME" --project "$PROJECT_ID" --location "$REGION" >/dev/null 2>&1; then
  gcloud tasks queues update "$QUEUE_NAME" --project "$PROJECT_ID" --location "$REGION" \
    --max-dispatches-per-second "$MAX_DISPATCHES_PER_SECOND" \
    --max-concurrent-dispatches "$MAX_CONCURRENT_DISPATCHES" \
    --max-attempts 12 --min-backoff 60s --max-backoff 3600s --max-doublings 5 --quiet
else
  gcloud tasks queues create "$QUEUE_NAME" --project "$PROJECT_ID" --location "$REGION" \
    --max-dispatches-per-second "$MAX_DISPATCHES_PER_SECOND" \
    --max-concurrent-dispatches "$MAX_CONCURRENT_DISPATCHES" \
    --max-attempts 12 --min-backoff 60s --max-backoff 3600s --max-doublings 5 --quiet
fi

gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${WORKER_SERVICE_ACCOUNT}" --role="roles/datastore.user" --condition=None --quiet
for enqueuer in "$API_SERVICE_ACCOUNT" "$WORKER_SERVICE_ACCOUNT"; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${enqueuer}" --role="roles/cloudtasks.enqueuer" --condition=None --quiet
  gcloud iam service-accounts add-iam-policy-binding "$TASKS_INVOKER_SERVICE_ACCOUNT" --project "$PROJECT_ID" \
    --member="serviceAccount:${enqueuer}" --role="roles/iam.serviceAccountUser" --quiet
done

for invoker in "$TASKS_INVOKER_SERVICE_ACCOUNT" "$SCHEDULER_INVOKER_SERVICE_ACCOUNT"; do
  gcloud run services add-iam-policy-binding "$WORKER_SERVICE" --project "$PROJECT_ID" --region "$REGION" \
    --member="serviceAccount:${invoker}" --role="roles/run.invoker" --quiet
done

for secret_name in "spa-flowaccount-client-id-${DEPLOY_ENVIRONMENT}" "spa-flowaccount-client-secret-${DEPLOY_ENVIRONMENT}"; do
  gcloud secrets describe "$secret_name" --project "$PROJECT_ID" >/dev/null
  gcloud secrets add-iam-policy-binding "$secret_name" --project "$PROJECT_ID" \
    --member="serviceAccount:${WORKER_SERVICE_ACCOUNT}" --role="roles/secretmanager.secretAccessor" --quiet
done

SCHEDULER_URI="${WORKER_URL%/}/internal/v1/accounting-runs:nightly"
if gcloud scheduler jobs describe "$SCHEDULER_JOB" --project "$PROJECT_ID" --location "$REGION" >/dev/null 2>&1; then
  gcloud scheduler jobs update http "$SCHEDULER_JOB" --project "$PROJECT_ID" --location "$REGION" \
    --schedule "15 0 * * *" --time-zone "Asia/Bangkok" --uri "$SCHEDULER_URI" --http-method POST \
    --oidc-service-account-email "$SCHEDULER_INVOKER_SERVICE_ACCOUNT" --oidc-token-audience "$WORKER_URL" --quiet
else
  gcloud scheduler jobs create http "$SCHEDULER_JOB" --project "$PROJECT_ID" --location "$REGION" \
    --schedule "15 0 * * *" --time-zone "Asia/Bangkok" --uri "$SCHEDULER_URI" --http-method POST \
    --oidc-service-account-email "$SCHEDULER_INVOKER_SERVICE_ACCOUNT" --oidc-token-audience "$WORKER_URL" --quiet
fi

if [[ "$ENABLE_SCHEDULER" == "true" ]]; then
  gcloud scheduler jobs resume "$SCHEDULER_JOB" --project "$PROJECT_ID" --location "$REGION" --quiet || true
else
  gcloud scheduler jobs pause "$SCHEDULER_JOB" --project "$PROJECT_ID" --location "$REGION" --quiet
fi

echo "Accounting runtime provisioned for ${DEPLOY_ENVIRONMENT}; scheduler enabled=${ENABLE_SCHEDULER}."
echo "Queue: ${QUEUE_NAME}"
echo "Tasks invoker: ${TASKS_INVOKER_SERVICE_ACCOUNT}"
