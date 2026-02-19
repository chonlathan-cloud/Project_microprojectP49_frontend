#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-the49-487609}"
REGION="${REGION:-asia-southeast1}"
SERVICE_NAME="${SERVICE_NAME:-the49-frontend}"
SOURCE_DIR="${SOURCE_DIR:-frontend}"
ENV_FILE="${ENV_FILE:-frontend/.env.local}"
BACKEND_SERVICE_NAME="${BACKEND_SERVICE_NAME:-the49-backend}"
BUILD_SERVICE_ACCOUNT="${BUILD_SERVICE_ACCOUNT:-project-the49@the49-487609.iam.gserviceaccount.com}"

# AUTH_MODE: impersonation | key | none
AUTH_MODE="${AUTH_MODE:-impersonation}"
IMPERSONATE_SERVICE_ACCOUNT="${IMPERSONATE_SERVICE_ACCOUNT:-project-the49@the49-487609.iam.gserviceaccount.com}"
SERVICE_ACCOUNT_KEY_PATH="${SERVICE_ACCOUNT_KEY_PATH:-}"

ALLOW_UNAUTHENTICATED="${ALLOW_UNAUTHENTICATED:-true}"
CHECK_MAIN_BRANCH="${CHECK_MAIN_BRANCH:-true}"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: '$1' is required but not installed."
    exit 1
  }
}

need_cmd gcloud
need_cmd git
need_cmd python3

if [[ "$CHECK_MAIN_BRANCH" == "true" ]]; then
  current_branch="$(git rev-parse --abbrev-ref HEAD)"
  if [[ "$current_branch" != "main" ]]; then
    echo "ERROR: Current branch is '$current_branch'. Deploy is allowed only from 'main'."
    echo "Set CHECK_MAIN_BRANCH=false to bypass."
    exit 1
  fi
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: ENV file not found: $ENV_FILE"
  exit 1
fi

if [[ -z "$BUILD_SERVICE_ACCOUNT" ]]; then
  echo "ERROR: BUILD_SERVICE_ACCOUNT must not be empty."
  exit 1
fi

if [[ "$BUILD_SERVICE_ACCOUNT" == projects/*/serviceAccounts/* ]]; then
  BUILD_SERVICE_ACCOUNT_RESOURCE="$BUILD_SERVICE_ACCOUNT"
elif [[ "$BUILD_SERVICE_ACCOUNT" == *"@"* ]]; then
  BUILD_SERVICE_ACCOUNT_RESOURCE="projects/${PROJECT_ID}/serviceAccounts/${BUILD_SERVICE_ACCOUNT}"
else
  echo "ERROR: BUILD_SERVICE_ACCOUNT must be either an email or"
  echo "projects/<projectId>/serviceAccounts/<serviceAccount>."
  exit 1
fi

GCLOUD_AUTH_ARGS=()
case "$AUTH_MODE" in
  impersonation)
    GCLOUD_AUTH_ARGS+=(--impersonate-service-account="$IMPERSONATE_SERVICE_ACCOUNT")
    ;;
  key)
    if [[ -z "$SERVICE_ACCOUNT_KEY_PATH" || ! -f "$SERVICE_ACCOUNT_KEY_PATH" ]]; then
      echo "ERROR: SERVICE_ACCOUNT_KEY_PATH is missing or file does not exist."
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

backend_url="${NEXT_PUBLIC_BACKEND_URL:-}"
if [[ -z "$backend_url" ]]; then
  backend_url="$(
    gcloud "${GCLOUD_AUTH_ARGS[@]}" run services describe "$BACKEND_SERVICE_NAME" \
      --project "$PROJECT_ID" \
      --region "$REGION" \
      --format='value(status.url)' 2>/dev/null || true
  )"
fi

if [[ -z "$backend_url" ]]; then
  echo "ERROR: Could not resolve backend URL."
  echo "Set NEXT_PUBLIC_BACKEND_URL explicitly, or deploy backend first."
  exit 1
fi

tmp_env_yaml="$(mktemp /tmp/the49_frontend_env.XXXXXX.yaml)"
cleanup() {
  rm -f "$tmp_env_yaml"
}
trap cleanup EXIT

python3 - "$ENV_FILE" "$tmp_env_yaml" "$backend_url" <<'PY'
import json
import re
import sys
from pathlib import Path

src = Path(sys.argv[1])
dst = Path(sys.argv[2])
backend_url = sys.argv[3]
lines = src.read_text(encoding="utf-8").splitlines()
env = {}

pattern = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
for raw in lines:
    line = raw.strip()
    if not line or line.startswith("#"):
        continue
    if line.startswith("export "):
        line = line[len("export "):].strip()
    if "=" not in line:
        continue
    key, value = line.split("=", 1)
    key = key.strip()
    value = value.strip()
    if not pattern.match(key):
        continue
    if not key.startswith("NEXT_PUBLIC_"):
        continue
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        value = value[1:-1]
    env[key] = value

# Always override backend URL for deployed frontend.
env["NEXT_PUBLIC_BACKEND_URL"] = backend_url.rstrip("/")

with dst.open("w", encoding="utf-8") as f:
    for k, v in env.items():
        f.write(f"{k}: {json.dumps(v, ensure_ascii=False)}\n")
PY

echo "Deploying frontend service '$SERVICE_NAME' to Cloud Run..."
echo "Using build service account: $BUILD_SERVICE_ACCOUNT_RESOURCE"
deploy_args=(
  run deploy "$SERVICE_NAME"
  --source "$SOURCE_DIR"
  --project "$PROJECT_ID"
  --region "$REGION"
  --build-service-account "$BUILD_SERVICE_ACCOUNT_RESOURCE"
  --env-vars-file "$tmp_env_yaml"
  --quiet
)

if [[ "$ALLOW_UNAUTHENTICATED" == "true" ]]; then
  deploy_args+=(--allow-unauthenticated)
else
  deploy_args+=(--no-allow-unauthenticated)
fi

gcloud "${GCLOUD_AUTH_ARGS[@]}" "${deploy_args[@]}"

frontend_url="$(
  gcloud "${GCLOUD_AUTH_ARGS[@]}" run services describe "$SERVICE_NAME" \
    --project "$PROJECT_ID" \
    --region "$REGION" \
    --format='value(status.url)'
)"

echo "Frontend deployed successfully."
echo "Service URL: $frontend_url"
