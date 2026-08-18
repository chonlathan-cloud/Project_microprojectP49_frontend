#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-the49-487609}"
REGION="${REGION:-asia-southeast1}"
APP_ENV="${APP_ENV:-production}"
BUCKET_NAME="${SERVICE_ASSETS_BUCKET:-${PROJECT_ID}-spa-service-assets-${APP_ENV}}"
API_SERVICE_ACCOUNT="${API_SERVICE_ACCOUNT:-spa-api-sa@${PROJECT_ID}.iam.gserviceaccount.com}"
APPLY=false

usage() {
  echo "Usage: $0 [--apply]"
  echo "Without --apply, prints the target configuration and makes no changes."
}

for argument in "$@"; do
  case "$argument" in
    --apply) APPLY=true ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: Unknown argument: $argument" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "$APPLY" != "true" ]]; then
  echo "PLAN bucket=gs://${BUCKET_NAME} location=${REGION} runtime=${API_SERVICE_ACCOUNT}"
  echo "Run with --apply to create/update the bucket and IAM binding."
  exit 0
fi

if ! gcloud storage buckets describe "gs://${BUCKET_NAME}" --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://${BUCKET_NAME}" \
    --project="$PROJECT_ID" \
    --location="$REGION" \
    --uniform-bucket-level-access \
    --public-access-prevention
fi

gcloud storage buckets update "gs://${BUCKET_NAME}" \
  --project="$PROJECT_ID" \
  --uniform-bucket-level-access \
  --public-access-prevention

gcloud storage buckets add-iam-policy-binding "gs://${BUCKET_NAME}" \
  --member="serviceAccount:${API_SERVICE_ACCOUNT}" \
  --role="roles/storage.objectUser"

echo "Configured private service-assets bucket gs://${BUCKET_NAME} for ${API_SERVICE_ACCOUNT}."
