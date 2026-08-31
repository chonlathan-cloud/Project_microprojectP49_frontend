#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd)"

PROJECT_ID="${PROJECT_ID:-the49-487609}"
REGION="${REGION:-asia-southeast1}"
SERVICE_NAME="${SERVICE_NAME:-spa-accounting-worker-test}"
SOURCE_DIR="${SOURCE_DIR:-$SCRIPT_DIR/services/accounting-worker}"
ARTIFACT_REPOSITORY="${ARTIFACT_REPOSITORY:-spa}"
IMAGE_NAME="${IMAGE_NAME:-spa-accounting-worker}"
IMAGE_TAG="${IMAGE_TAG:-}"
RUNTIME_SERVICE_ACCOUNT="${RUNTIME_SERVICE_ACCOUNT:-spa-accounting-worker-sa@${PROJECT_ID}.iam.gserviceaccount.com}"
IMPERSONATE_SERVICE_ACCOUNT="${IMPERSONATE_SERVICE_ACCOUNT:-project-the49@the49-487609.iam.gserviceaccount.com}"
CHECK_MAIN_BRANCH="${CHECK_MAIN_BRANCH:-true}"
DEPLOY_ENVIRONMENT="${DEPLOY_ENVIRONMENT:-test}"
case "$DEPLOY_ENVIRONMENT" in
  test | prod) ;;
  *)
    echo "ERROR: DEPLOY_ENVIRONMENT must be one of: test | prod"
    exit 1
    ;;
esac
FLOWACCOUNT_SYNC_ENABLED="${FLOWACCOUNT_SYNC_ENABLED:-false}"
ENV_FILE="${ENV_FILE:-$SOURCE_DIR/.env-${DEPLOY_ENVIRONMENT}}"
FLOWACCOUNT_CLIENT_ID_SECRET="${FLOWACCOUNT_CLIENT_ID_SECRET:-spa-flowaccount-client-id-${DEPLOY_ENVIRONMENT}}"
FLOWACCOUNT_CLIENT_SECRET="${FLOWACCOUNT_CLIENT_SECRET:-spa-flowaccount-client-secret-${DEPLOY_ENVIRONMENT}}"

for required_command in gcloud git python3; do
  if ! command -v "$required_command" >/dev/null 2>&1; then
    echo "ERROR: '$required_command' is required."
    exit 1
  fi
done

cd "$REPO_ROOT"
if [[ "$CHECK_MAIN_BRANCH" == "true" && "$(git branch --show-current)" != "main" ]]; then
  echo "ERROR: Accounting Worker deploys require the main branch."
  exit 1
fi
if [[ ! -f "$SOURCE_DIR/Dockerfile" || ! -f "$SOURCE_DIR/uv.lock" ]]; then
  echo "ERROR: Accounting Worker source or lockfile is missing."
  exit 1
fi
if [[ -z "$IMAGE_TAG" ]]; then
  IMAGE_TAG="$(git rev-parse --short=12 HEAD)-$(date -u +%Y%m%d%H%M%S)"
fi

GCLOUD_ARGS=(--impersonate-service-account="$IMPERSONATE_SERVICE_ACCOUNT")
IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPOSITORY}/${IMAGE_NAME}:${IMAGE_TAG}"
tmp_env_yaml="$(mktemp "${TMPDIR:-/tmp}/spa_accounting_worker_env.XXXXXX.yaml")"
cleanup() {
  rm -f "$tmp_env_yaml"
}
trap cleanup EXIT

python3 - "$ENV_FILE" "$tmp_env_yaml" "$DEPLOY_ENVIRONMENT" "$FLOWACCOUNT_SYNC_ENABLED" <<'PY'
import json
import re
import sys
from pathlib import Path

source = Path(sys.argv[1])
destination = Path(sys.argv[2])
environment = {
    "FLOWACCOUNT_ENVIRONMENT": sys.argv[3],
    "FLOWACCOUNT_SYNC_ENABLED": sys.argv[4],
}
valid_key = re.compile(r"^FLOWACCOUNT_[A-Z0-9_]+$")
secret_keys = {"FLOWACCOUNT_CLIENT_ID", "FLOWACCOUNT_CLIENT_SECRET"}
if source.exists():
    for raw_line in source.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.removeprefix("export ").strip()
        value = value.strip()
        if valid_key.match(key) and key not in secret_keys:
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            environment[key] = value
with destination.open("w", encoding="utf-8") as output:
    for key, value in environment.items():
        output.write(f"{key}: {json.dumps(value, ensure_ascii=False)}\n")
PY

if ! gcloud "${GCLOUD_ARGS[@]}" artifacts repositories describe "$ARTIFACT_REPOSITORY" \
  --project "$PROJECT_ID" --location "$REGION" >/dev/null 2>&1; then
  echo "ERROR: Artifact Registry '$ARTIFACT_REPOSITORY' does not exist in '$REGION'."
  exit 1
fi

echo "Building Accounting Worker image..."
gcloud "${GCLOUD_ARGS[@]}" builds submit "$SOURCE_DIR" \
  --project "$PROJECT_ID" \
  --tag "$IMAGE_URI" \
  --quiet

echo "Deploying private Accounting Worker (sync=${FLOWACCOUNT_SYNC_ENABLED})..."
deploy_args=(run deploy "$SERVICE_NAME" \
  --image "$IMAGE_URI" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --service-account "$RUNTIME_SERVICE_ACCOUNT" \
  --no-allow-unauthenticated \
  --ingress internal \
  --execution-environment gen2 \
  --cpu 1 \
  --memory 512Mi \
  --concurrency 2 \
  --min-instances 0 \
  --max-instances 5 \
  --timeout 60s \
  --env-vars-file "$tmp_env_yaml" \
  --labels "application=spa,component=accounting-worker,environment=${DEPLOY_ENVIRONMENT}" \
  --quiet)
if [[ "$FLOWACCOUNT_SYNC_ENABLED" == "true" ]]; then
  deploy_args+=(--update-secrets "FLOWACCOUNT_CLIENT_ID=${FLOWACCOUNT_CLIENT_ID_SECRET}:latest,FLOWACCOUNT_CLIENT_SECRET=${FLOWACCOUNT_CLIENT_SECRET}:latest")
fi
gcloud "${GCLOUD_ARGS[@]}" "${deploy_args[@]}"

echo "Accounting Worker deployed (FlowAccount sync=${FLOWACCOUNT_SYNC_ENABLED})."
echo "Image: $IMAGE_URI"
