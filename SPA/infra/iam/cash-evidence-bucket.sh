#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-the49-487609}"
REGION="${REGION:-asia-southeast1}"
ENVIRONMENT="${ENVIRONMENT:-test}"
RUNTIME_SERVICE_ACCOUNT="${RUNTIME_SERVICE_ACCOUNT:-spa-api-sa@${PROJECT_ID}.iam.gserviceaccount.com}"
APPLY="${APPLY:-false}"

case "$ENVIRONMENT" in
  test) SUFFIX="test" ;;
  prod | production) SUFFIX="production" ;;
  *) echo "ERROR: ENVIRONMENT must be test or prod" >&2; exit 1 ;;
esac

BUCKET="${CASH_EVIDENCE_BUCKET:-${PROJECT_ID}-spa-cash-evidence-${SUFFIX}}"
if [[ "$APPLY" != "true" ]]; then
  echo "Dry run. Review and rerun with APPLY=true:"
  echo "  create private UBLA bucket: gs://${BUCKET} (${REGION})"
  echo "  grant roles/storage.objectAdmin to ${RUNTIME_SERVICE_ACCOUNT} on the bucket"
  echo "  grant roles/iam.serviceAccountTokenCreator to the runtime identity on itself"
  echo "Then apply SPA/infra/iam/cash-evidence-cors.json to gs://${BUCKET}."
  exit 0
fi

gcloud storage buckets create "gs://${BUCKET}" \
  --project="$PROJECT_ID" \
  --location="$REGION" \
  --uniform-bucket-level-access \
  --public-access-prevention
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${RUNTIME_SERVICE_ACCOUNT}" \
  --role="roles/storage.objectAdmin"
gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_SERVICE_ACCOUNT" \
  --project="$PROJECT_ID" \
  --member="serviceAccount:${RUNTIME_SERVICE_ACCOUNT}" \
  --role="roles/iam.serviceAccountTokenCreator"
gcloud storage buckets update "gs://${BUCKET}" \
  --cors-file="$(dirname "$0")/cash-evidence-cors.json"
echo "Cash evidence bucket ready: gs://${BUCKET}"
