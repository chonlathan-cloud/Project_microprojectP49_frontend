#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd)"

PROJECT_ID="${PROJECT_ID:-the49-487609}"
REGION="${REGION:-asia-southeast1}"
SERVICE_NAME="${SERVICE_NAME:-spa-admin-web}"
SOURCE_DIR="${SOURCE_DIR:-$SCRIPT_DIR}"
DOCKERFILE="${DOCKERFILE:-apps/admin-web/Dockerfile}"
ENV_FILE="${ENV_FILE:-$SCRIPT_DIR/apps/admin-web/.env}"
REQUIRE_ENV_FILE="${REQUIRE_ENV_FILE:-false}"
SPA_API_URL="${SPA_API_URL:-}"

if [[ "$SERVICE_NAME" != *-test ]]; then
  if [[ -z "$SPA_API_URL" ]]; then
    echo "ERROR: SPA_API_URL must be set explicitly for a production deployment." >&2
    exit 1
  fi
  if [[ "$SPA_API_URL" == *"spa-api-test"* ]]; then
    echo "ERROR: Production Admin Web cannot target spa-api-test." >&2
    exit 1
  fi
fi

ARTIFACT_REPOSITORY="${ARTIFACT_REPOSITORY:-spa}"
IMAGE_NAME="${IMAGE_NAME:-spa-admin-web}"
IMAGE_TAG="${IMAGE_TAG:-}"
CREATE_ARTIFACT_REPOSITORY="${CREATE_ARTIFACT_REPOSITORY:-true}"

BUILD_SERVICE_ACCOUNT="${BUILD_SERVICE_ACCOUNT:-project-the49@the49-487609.iam.gserviceaccount.com}"
RUNTIME_SERVICE_ACCOUNT="${RUNTIME_SERVICE_ACCOUNT:-spa-admin-web-sa@${PROJECT_ID}.iam.gserviceaccount.com}"

# AUTH_MODE: impersonation | key | none
AUTH_MODE="${AUTH_MODE:-impersonation}"
IMPERSONATE_SERVICE_ACCOUNT="${IMPERSONATE_SERVICE_ACCOUNT:-project-the49@the49-487609.iam.gserviceaccount.com}"
SERVICE_ACCOUNT_KEY_PATH="${SERVICE_ACCOUNT_KEY_PATH:-}"

ALLOW_UNAUTHENTICATED="${ALLOW_UNAUTHENTICATED:-true}"
CHECK_MAIN_BRANCH="${CHECK_MAIN_BRANCH:-true}"
REQUIRE_CLEAN_WORKTREE="${REQUIRE_CLEAN_WORKTREE:-true}"
CPU="${CPU:-1}"
MEMORY="${MEMORY:-512Mi}"
CONCURRENCY="${CONCURRENCY:-40}"
MIN_INSTANCES="${MIN_INSTANCES:-0}"
MAX_INSTANCES="${MAX_INSTANCES:-3}"
TIMEOUT="${TIMEOUT:-60s}"
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
tmp_build_config="$(mktemp "${TMPDIR:-/tmp}/spa_admin_web_build.XXXXXX.yaml")"
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
  tmp_env_yaml="$(mktemp "${TMPDIR:-/tmp}/spa_admin_web_env.XXXXXX.yaml")"
  python3 - "$ENV_FILE" "$tmp_env_yaml" "$SPA_API_URL" <<'PY'
import json
import re
import sys
from pathlib import Path

source = Path(sys.argv[1])
destination = Path(sys.argv[2])
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
    if not valid_key.match(key) or not (key.startswith("NEXT_PUBLIC_") or key == "SPA_API_URL"):
        continue
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    environment[key] = value

if sys.argv[3]:
    environment["SPA_API_URL"] = sys.argv[3]

with destination.open("w", encoding="utf-8") as output:
    for key, value in environment.items():
        output.write(f"{key}: {json.dumps(value, ensure_ascii=False)}\n")
PY
  env_args+=(--env-vars-file "$tmp_env_yaml")
elif [[ "$REQUIRE_ENV_FILE" == "true" ]]; then
  echo "ERROR: Environment file not found: $ENV_FILE"
  exit 1
else
  if [[ -n "$SPA_API_URL" ]]; then
    tmp_env_yaml="$(mktemp "${TMPDIR:-/tmp}/spa_admin_env.XXXXXX.yaml")"
    python3 - "$tmp_env_yaml" "$SPA_API_URL" <<'PY'
import json
import sys
from pathlib import Path
Path(sys.argv[1]).write_text(f"SPA_API_URL: {json.dumps(sys.argv[2])}\n", encoding="utf-8")
PY
    env_args+=(--env-vars-file "$tmp_env_yaml")
  else
    echo "Environment file not found; deploying without optional public runtime variables: $ENV_FILE"
  fi
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
  --labels "application=spa,component=admin-web"
  --quiet
)
deploy_args+=("${env_args[@]}")

if [[ "$ALLOW_UNAUTHENTICATED" == "true" ]]; then
  deploy_args+=(--allow-unauthenticated)
else
  deploy_args+=(--no-allow-unauthenticated)
fi

echo "Deploying public Admin Web service '$SERVICE_NAME'..."
gcloud "${GCLOUD_AUTH_ARGS[@]}" "${deploy_args[@]}"

service_url="$(gcloud "${GCLOUD_AUTH_ARGS[@]}" run services describe "$SERVICE_NAME" \
  --project "$PROJECT_ID" --region "$REGION" --format='value(status.url)')"

echo "Admin Web deployed successfully."
echo "Image: $IMAGE_URI"
echo "Service URL: $service_url"
