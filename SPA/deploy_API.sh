#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd)"

PROJECT_ID="${PROJECT_ID:-the49-487609}"
REGION="${REGION:-asia-southeast1}"
SERVICE_NAME="${SERVICE_NAME:-spa-api}"
SOURCE_DIR="${SOURCE_DIR:-$SCRIPT_DIR/services/api}"
DOCKERFILE="${DOCKERFILE:-Dockerfile}"
ENV_FILE="${ENV_FILE:-$SCRIPT_DIR/services/api/.env}"
REQUIRE_ENV_FILE="${REQUIRE_ENV_FILE:-false}"
FIRESTORE_DATABASE="${FIRESTORE_DATABASE:-spa-db}"
APP_ENV="${APP_ENV:-production}"
SERVICE_ASSETS_BUCKET="${SERVICE_ASSETS_BUCKET:-${PROJECT_ID}-spa-service-assets-${APP_ENV}}"
LINE_CUSTOMER_MESSAGING_CHANNEL_SECRET_NAME="${LINE_CUSTOMER_MESSAGING_CHANNEL_SECRET_NAME:-spa-line-customer-messaging-channel-secret}"
LINE_ADMIN_MESSAGING_CHANNEL_SECRET_NAME="${LINE_ADMIN_MESSAGING_CHANNEL_SECRET_NAME:-spa-line-admin-messaging-channel-secret}"

ARTIFACT_REPOSITORY="${ARTIFACT_REPOSITORY:-spa}"
IMAGE_NAME="${IMAGE_NAME:-spa-api}"
IMAGE_TAG="${IMAGE_TAG:-}"
CREATE_ARTIFACT_REPOSITORY="${CREATE_ARTIFACT_REPOSITORY:-true}"

BUILD_SERVICE_ACCOUNT="${BUILD_SERVICE_ACCOUNT:-project-the49@the49-487609.iam.gserviceaccount.com}"
RUNTIME_SERVICE_ACCOUNT="${RUNTIME_SERVICE_ACCOUNT:-spa-api-sa@${PROJECT_ID}.iam.gserviceaccount.com}"

# AUTH_MODE: impersonation | key | none
AUTH_MODE="${AUTH_MODE:-impersonation}"
IMPERSONATE_SERVICE_ACCOUNT="${IMPERSONATE_SERVICE_ACCOUNT:-project-the49@the49-487609.iam.gserviceaccount.com}"
SERVICE_ACCOUNT_KEY_PATH="${SERVICE_ACCOUNT_KEY_PATH:-}"

ALLOW_UNAUTHENTICATED="${ALLOW_UNAUTHENTICATED:-true}"
CHECK_MAIN_BRANCH="${CHECK_MAIN_BRANCH:-true}"
REQUIRE_CLEAN_WORKTREE="${REQUIRE_CLEAN_WORKTREE:-true}"
CPU="${CPU:-1}"
MEMORY="${MEMORY:-1Gi}"
CONCURRENCY="${CONCURRENCY:-40}"
MIN_INSTANCES="${MIN_INSTANCES:-1}"
MAX_INSTANCES="${MAX_INSTANCES:-10}"
TIMEOUT="${TIMEOUT:-30s}"
INGRESS="${INGRESS:-all}"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: '$1' is required but not installed."
    exit 1
  }
}

need_cmd gcloud
need_cmd git
need_cmd python3

cd "$REPO_ROOT"

if [[ "$CHECK_MAIN_BRANCH" == "true" ]]; then
  current_branch="$(git branch --show-current)"
  if [[ "$current_branch" != "main" ]]; then
    echo "ERROR: Current branch is '$current_branch'. Production deploys are allowed only from 'main'."
    echo "Set CHECK_MAIN_BRANCH=false only when deliberately bypassing this safety guard."
    exit 1
  fi
fi

if [[ "$REQUIRE_CLEAN_WORKTREE" == "true" ]] && [[ -n "$(git status --porcelain -- "$SCRIPT_DIR")" ]]; then
  echo "ERROR: SPA worktree has uncommitted changes. Production deploy requires a traceable clean source tree."
  echo "Set REQUIRE_CLEAN_WORKTREE=false only for an isolated Test deployment."
  exit 1
fi

if [[ ! -f "$SOURCE_DIR/$DOCKERFILE" ]]; then
  echo "ERROR: Dockerfile not found: $SOURCE_DIR/$DOCKERFILE"
  exit 1
fi

if [[ -z "$IMAGE_TAG" ]]; then
  IMAGE_TAG="$(git rev-parse --short=12 HEAD)-$(date -u +%Y%m%d%H%M%S)"
fi

if [[ "$BUILD_SERVICE_ACCOUNT" == projects/*/serviceAccounts/* ]]; then
  BUILD_SERVICE_ACCOUNT_RESOURCE="$BUILD_SERVICE_ACCOUNT"
elif [[ "$BUILD_SERVICE_ACCOUNT" == *"@"* ]]; then
  BUILD_SERVICE_ACCOUNT_RESOURCE="projects/${PROJECT_ID}/serviceAccounts/${BUILD_SERVICE_ACCOUNT}"
else
  echo "ERROR: BUILD_SERVICE_ACCOUNT must be an email or a full service-account resource name."
  exit 1
fi

GCLOUD_AUTH_ARGS=()
case "$AUTH_MODE" in
  impersonation)
    GCLOUD_AUTH_ARGS+=(--impersonate-service-account="$IMPERSONATE_SERVICE_ACCOUNT")
    ;;
  key)
    if [[ -z "$SERVICE_ACCOUNT_KEY_PATH" || ! -f "$SERVICE_ACCOUNT_KEY_PATH" ]]; then
      echo "ERROR: SERVICE_ACCOUNT_KEY_PATH is missing or does not exist."
      exit 1
    fi
    gcloud auth activate-service-account --key-file="$SERVICE_ACCOUNT_KEY_PATH" --project="$PROJECT_ID" >/dev/null
    ;;
  none)
    ;;
  *)
    echo "ERROR: AUTH_MODE must be one of: impersonation | key | none"
    exit 1
    ;;
esac

if ! gcloud "${GCLOUD_AUTH_ARGS[@]}" artifacts repositories describe "$ARTIFACT_REPOSITORY" \
  --project "$PROJECT_ID" --location "$REGION" >/dev/null 2>&1; then
  if [[ "$CREATE_ARTIFACT_REPOSITORY" != "true" ]]; then
    echo "ERROR: Artifact Registry repository '$ARTIFACT_REPOSITORY' was not found in '$REGION'."
    exit 1
  fi
  echo "Creating Artifact Registry repository '$ARTIFACT_REPOSITORY'..."
  gcloud "${GCLOUD_AUTH_ARGS[@]}" artifacts repositories create "$ARTIFACT_REPOSITORY" \
    --project "$PROJECT_ID" \
    --location "$REGION" \
    --repository-format docker \
    --description "SPA Cloud Run images" \
    --quiet
fi

IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPOSITORY}/${IMAGE_NAME}:${IMAGE_TAG}"
tmp_build_config="$(mktemp "${TMPDIR:-/tmp}/spa_api_build.XXXXXX.yaml")"
tmp_env_yaml=""
cleanup() {
  rm -f "$tmp_build_config"
  if [[ -n "$tmp_env_yaml" ]]; then
    rm -f "$tmp_env_yaml"
  fi
}
trap cleanup EXIT

cat >"$tmp_build_config" <<YAML
steps:
  - name: gcr.io/cloud-builders/docker
    args: ["build", "--file", "$DOCKERFILE", "--tag", "$IMAGE_URI", "."]
images:
  - "$IMAGE_URI"
options:
  logging: CLOUD_LOGGING_ONLY
YAML

env_args=()
if [[ -f "$ENV_FILE" ]]; then
  tmp_env_yaml="$(mktemp "${TMPDIR:-/tmp}/spa_api_env.XXXXXX.yaml")"
  python3 - "$ENV_FILE" "$tmp_env_yaml" "$FIRESTORE_DATABASE" "$APP_ENV" "$SERVICE_ASSETS_BUCKET" <<'PY'
import json
import re
import sys
from pathlib import Path

source = Path(sys.argv[1])
destination = Path(sys.argv[2])
firestore_database = sys.argv[3]
app_env = sys.argv[4]
service_assets_bucket = sys.argv[5]
valid_key = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
environment = {}

for raw_line in source.read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#"):
        continue
    if line.startswith("export "):
        line = line[len("export "):].strip()
    if "=" not in line:
        continue
    key, value = line.split("=", 1)
    key = key.strip()
    value = value.strip()
    if not valid_key.match(key):
        continue
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    environment[key] = value

environment["FIRESTORE_DATABASE"] = firestore_database
environment["APP_ENV"] = app_env
environment["SERVICE_ASSETS_BUCKET"] = service_assets_bucket

with destination.open("w", encoding="utf-8") as output:
    for key, value in environment.items():
        output.write(f"{key}: {json.dumps(value, ensure_ascii=False)}\n")
PY
  env_args+=(--env-vars-file "$tmp_env_yaml")
elif [[ "$REQUIRE_ENV_FILE" == "true" ]]; then
  echo "ERROR: Environment file not found: $ENV_FILE"
  exit 1
else
  echo "Environment file not found; using FIRESTORE_DATABASE=$FIRESTORE_DATABASE: $ENV_FILE"
  tmp_env_yaml="$(mktemp "${TMPDIR:-/tmp}/spa_api_env.XXXXXX.yaml")"
  python3 - "$tmp_env_yaml" "$FIRESTORE_DATABASE" "$APP_ENV" "$SERVICE_ASSETS_BUCKET" <<'PY'
import json
import sys
from pathlib import Path

destination = Path(sys.argv[1])
destination.write_text(
    "\n".join(
        [
            f"FIRESTORE_DATABASE: {json.dumps(sys.argv[2])}",
            f"APP_ENV: {json.dumps(sys.argv[3])}",
            f"SERVICE_ASSETS_BUCKET: {json.dumps(sys.argv[4])}",
            "",
        ]
    ),
    encoding="utf-8",
)
PY
  env_args+=(--env-vars-file "$tmp_env_yaml")
fi

echo "Building '$IMAGE_URI' with Cloud Build..."
gcloud "${GCLOUD_AUTH_ARGS[@]}" builds submit "$SOURCE_DIR" \
  --project "$PROJECT_ID" \
  --config "$tmp_build_config" \
  --service-account "$BUILD_SERVICE_ACCOUNT_RESOURCE" \
  --quiet

deploy_args=(
  run deploy "$SERVICE_NAME"
  --image "$IMAGE_URI"
  --project "$PROJECT_ID"
  --region "$REGION"
  --service-account "$RUNTIME_SERVICE_ACCOUNT"
  --cpu "$CPU"
  --memory "$MEMORY"
  --concurrency "$CONCURRENCY"
  --min-instances "$MIN_INSTANCES"
  --max-instances "$MAX_INSTANCES"
  --timeout "$TIMEOUT"
  --port 8080
  --ingress "$INGRESS"
  --execution-environment gen2
  --labels "application=spa,component=api"
  --set-secrets "LINE_CUSTOMER_MESSAGING_CHANNEL_SECRET=${LINE_CUSTOMER_MESSAGING_CHANNEL_SECRET_NAME}:latest,LINE_ADMIN_MESSAGING_CHANNEL_SECRET=${LINE_ADMIN_MESSAGING_CHANNEL_SECRET_NAME}:latest,LINE_CUSTOMER_LOGIN_CHANNEL_ID=spa-line-customer-login-channel-id:latest,LINE_ADMIN_GROUP_ID=spa-line-admin-group-id:latest"
  --quiet
)
deploy_args+=("${env_args[@]}")

if [[ "$ALLOW_UNAUTHENTICATED" == "true" ]]; then
  deploy_args+=(--allow-unauthenticated)
else
  deploy_args+=(--no-allow-unauthenticated)
fi

echo "Deploying public SPA API service '$SERVICE_NAME'..."
gcloud "${GCLOUD_AUTH_ARGS[@]}" "${deploy_args[@]}"

service_url="$(gcloud "${GCLOUD_AUTH_ARGS[@]}" run services describe "$SERVICE_NAME" \
  --project "$PROJECT_ID" --region "$REGION" --format='value(status.url)')"

echo "SPA API deployed successfully."
echo "Image: $IMAGE_URI"
echo "Service URL: $service_url"
