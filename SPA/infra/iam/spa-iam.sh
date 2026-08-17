#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-the49-487609}"
API_SERVICE_ACCOUNT="${API_SERVICE_ACCOUNT:-spa-api-sa@${PROJECT_ID}.iam.gserviceaccount.com}"
WORKER_SERVICE_ACCOUNT="${WORKER_SERVICE_ACCOUNT:-spa-worker-sa@${PROJECT_ID}.iam.gserviceaccount.com}"

for service_account in "$API_SERVICE_ACCOUNT" "$WORKER_SERVICE_ACCOUNT"; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${service_account}" \
    --role="roles/datastore.user" \
    --quiet
done

echo "Granted Firestore access to SPA API and Worker service accounts."
