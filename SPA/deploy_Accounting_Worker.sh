#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd)"

PROJECT_ID="${PROJECT_ID:-the49-487609}"
REGION="${REGION:-asia-southeast1}"
SERVICE_NAME="${SERVICE_NAME:-}"
SOURCE_DIR="${SOURCE_DIR:-$SCRIPT_DIR/services/accounting-worker}"
ARTIFACT_REPOSITORY="${ARTIFACT_REPOSITORY:-spa}"
IMAGE_NAME="${IMAGE_NAME:-spa-accounting-worker}"
IMAGE_TAG="${IMAGE_TAG:-}"
RUNTIME_SERVICE_ACCOUNT="${RUNTIME_SERVICE_ACCOUNT:-}"
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
if [[ -z "$SERVICE_NAME" ]]; then
  SERVICE_NAME="spa-accounting-worker${DEPLOY_ENVIRONMENT:+-${DEPLOY_ENVIRONMENT}}"
  [[ "$DEPLOY_ENVIRONMENT" == "prod" ]] && SERVICE_NAME="spa-accounting-worker"
fi
if [[ -z "$RUNTIME_SERVICE_ACCOUNT" ]]; then
  if [[ "$DEPLOY_ENVIRONMENT" == "test" ]]; then
    RUNTIME_SERVICE_ACCOUNT="spa-accounting-worker-test-sa@${PROJECT_ID}.iam.gserviceaccount.com"
  else
    RUNTIME_SERVICE_ACCOUNT="spa-accounting-worker-sa@${PROJECT_ID}.iam.gserviceaccount.com"
  fi
fi
if [[ "$DEPLOY_ENVIRONMENT" == "test" && "$SERVICE_NAME" != *-test ]]; then
  echo "ERROR: Test Accounting Worker service name must end in '-test'."
  exit 1
fi
if [[ "$DEPLOY_ENVIRONMENT" == "prod" && "$SERVICE_NAME" != "spa-accounting-worker" ]]; then
  echo "ERROR: Production Accounting Worker must use canonical service 'spa-accounting-worker'."
  exit 1
fi
ENV_FILE="${ENV_FILE:-$SOURCE_DIR/.env-${DEPLOY_ENVIRONMENT}}"
if [[ -z "${FLOWACCOUNT_SYNC_ENABLED+x}" ]]; then
  FLOWACCOUNT_SYNC_ENABLED="false"
  if [[ -f "$ENV_FILE" ]]; then
    while IFS= read -r raw_line; do
      line="${raw_line#export }"
      if [[ "$line" == FLOWACCOUNT_SYNC_ENABLED=* ]]; then
        FLOWACCOUNT_SYNC_ENABLED="${line#*=}"
        FLOWACCOUNT_SYNC_ENABLED="${FLOWACCOUNT_SYNC_ENABLED%\"}"
        FLOWACCOUNT_SYNC_ENABLED="${FLOWACCOUNT_SYNC_ENABLED#\"}"
        FLOWACCOUNT_SYNC_ENABLED="${FLOWACCOUNT_SYNC_ENABLED%\'}"
        FLOWACCOUNT_SYNC_ENABLED="${FLOWACCOUNT_SYNC_ENABLED#\'}"
      fi
    done < "$ENV_FILE"
  fi
fi
case "$FLOWACCOUNT_SYNC_ENABLED" in
  true | false) ;;
  *)
    echo "ERROR: FLOWACCOUNT_SYNC_ENABLED must be true or false."
    exit 1
    ;;
esac
FLOWACCOUNT_CLIENT_ID_SECRET="${FLOWACCOUNT_CLIENT_ID_SECRET:-spa-flowaccount-client-id-${DEPLOY_ENVIRONMENT}}"
FLOWACCOUNT_CLIENT_SECRET="${FLOWACCOUNT_CLIENT_SECRET:-spa-flowaccount-client-secret-${DEPLOY_ENVIRONMENT}}"
if [[ "$FLOWACCOUNT_CLIENT_ID_SECRET" != "spa-flowaccount-client-id-${DEPLOY_ENVIRONMENT}" \
  || "$FLOWACCOUNT_CLIENT_SECRET" != "spa-flowaccount-client-secret-${DEPLOY_ENVIRONMENT}" ]]; then
  echo "ERROR: FlowAccount secret names must match the selected deployment environment."
  exit 1
fi

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

if [[ "$FLOWACCOUNT_SYNC_ENABLED" == "true" ]]; then
  for secret_name in "$FLOWACCOUNT_CLIENT_ID_SECRET" "$FLOWACCOUNT_CLIENT_SECRET"; do
    latest_state="$(gcloud "${GCLOUD_ARGS[@]}" secrets versions describe latest \
      --secret "$secret_name" --project "$PROJECT_ID" --format='value(state)' 2>/dev/null || true)"
    if [[ "$latest_state" != "ENABLED" ]]; then
      echo "ERROR: Secret '$secret_name' has no enabled latest version."
      exit 1
    fi
    accessor_role="$(gcloud "${GCLOUD_ARGS[@]}" secrets get-iam-policy "$secret_name" \
      --project "$PROJECT_ID" --flatten='bindings[]' \
      --filter="bindings.role=roles/secretmanager.secretAccessor AND bindings.members=serviceAccount:${RUNTIME_SERVICE_ACCOUNT}" \
      --format='value(bindings.role)' 2>/dev/null || true)"
    if [[ "$accessor_role" != "roles/secretmanager.secretAccessor" ]]; then
      echo "ERROR: Runtime identity lacks direct Secret Accessor on '$secret_name'."
      exit 1
    fi
  done
fi

python3 - "$ENV_FILE" "$tmp_env_yaml" "$DEPLOY_ENVIRONMENT" "$FLOWACCOUNT_SYNC_ENABLED" <<'PY'
import json
import re
import sys
from pathlib import Path

source = Path(sys.argv[1])
destination = Path(sys.argv[2])
environment = {}
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
environment["FLOWACCOUNT_ENVIRONMENT"] = sys.argv[3]
environment["FLOWACCOUNT_SYNC_ENABLED"] = sys.argv[4]
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
build_id="$(gcloud "${GCLOUD_ARGS[@]}" builds submit "$SOURCE_DIR" \
  --project "$PROJECT_ID" \
  --tag "$IMAGE_URI" \
  --async \
  --format='value(id)' \
  --quiet)"
if [[ -z "$build_id" ]]; then
  echo "ERROR: Cloud Build did not return a build ID."
  exit 1
fi
while true; do
  build_status="$(gcloud "${GCLOUD_ARGS[@]}" builds describe "$build_id" \
    --project "$PROJECT_ID" --format='value(status)')"
  case "$build_status" in
    SUCCESS)
      break
      ;;
    FAILURE | INTERNAL_ERROR | TIMEOUT | CANCELLED | EXPIRED)
      echo "ERROR: Cloud Build '$build_id' finished with status '$build_status'."
      exit 1
      ;;
    *)
      echo "Cloud Build '$build_id' status: ${build_status:-UNKNOWN}"
      sleep 5
      ;;
  esac
done

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
