#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

export PATH="$HOME/.local/bin:$PATH"

if [ -f "$ROOT_DIR/.env.railway" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT_DIR/.env.railway"
  set +a
fi

if ! command -v railway >/dev/null 2>&1; then
  echo "ERROR: railway CLI is not installed. Install with: npm install -g @railway/cli --prefix ~/.local --allow-scripts=@railway/cli" >&2
  exit 1
fi

PROJECT_ID="9724a283-de00-488b-825d-fabb9186aca6"
ENVIRONMENT_NAME="production"
SERVICE_NAME="NHL-FUSION-SIGNAL"

echo "=== [1/4] Verifying Railway target (${SERVICE_NAME} in project brilliant-charisma / ${ENVIRONMENT_NAME}) ==="
railway link --project "$PROJECT_ID" --environment "$ENVIRONMENT_NAME" --service "$SERVICE_NAME" --json >/dev/null

PUBLIC_DOMAIN="$(railway domain list --service "$SERVICE_NAME" --environment "$ENVIRONMENT_NAME" --project "$PROJECT_ID" --json | jq -r '.domains[0].domain // empty')"
if [ -z "$PUBLIC_DOMAIN" ]; then
  PUBLIC_DOMAIN="$(railway domain --service "$SERVICE_NAME" --environment "$ENVIRONMENT_NAME" --project "$PROJECT_ID" --port 8080 --json | jq -r '.domain // empty' | sed 's#^https\?://##')"
fi
PUBLIC_URL="https://${PUBLIC_DOMAIN#https://}"
echo "Target Service : ${SERVICE_NAME} (isolated from KALSHI-SIGNAL-HUB-SPORT)"
echo "Public URL     : ${PUBLIC_URL}"

echo "=== [2/4] Uploading & triggering detached Railway build ==="
railway up --detach --service "$SERVICE_NAME" --environment "$ENVIRONMENT_NAME" --project "$PROJECT_ID"

sleep 4
DEPLOY_ID="$(railway deployment list --service "$SERVICE_NAME" --environment "$ENVIRONMENT_NAME" --project "$PROJECT_ID" --limit 1 --json | jq -r '.[0].id // empty')"
echo "Deployment ID  : ${DEPLOY_ID:-pending}"

echo "=== [3/4] Monitoring Railway build & rollout to SUCCESS ==="
MAX_ATTEMPTS=90
ATTEMPT=0
while [ "$ATTEMPT" -lt "$MAX_ATTEMPTS" ]; do
  ATTEMPT=$((ATTEMPT + 1))
  DEP_JSON="$(railway deployment list --service "$SERVICE_NAME" --environment "$ENVIRONMENT_NAME" --project "$PROJECT_ID" --limit 1 --json)"
  CUR_ID="$(printf '%s' "$DEP_JSON" | jq -r '.[0].id // empty')"
  STATUS="$(printf '%s' "$DEP_JSON" | jq -r '.[0].status // "UNKNOWN"')"
  printf '[%s] (%d/%d) Deployment %s -> %s\n' "$(date -u +%H:%M:%S)" "$ATTEMPT" "$MAX_ATTEMPTS" "${CUR_ID:-unknown}" "$STATUS"

  case "$STATUS" in
    SUCCESS)
      echo "Railway deployment reached SUCCESS!"
      break
      ;;
    FAILED|CRASHED|REMOVED|CANCELED)
      echo "ERROR: Deployment ended with status=${STATUS}. Recent logs:" >&2
      railway logs --service "$SERVICE_NAME" --environment "$ENVIRONMENT_NAME" --lines 120 || true
      exit 1
      ;;
  esac

  if [ "$ATTEMPT" -ge "$MAX_ATTEMPTS" ]; then
    echo "ERROR: Timed out waiting for Railway deployment SUCCESS (last status=${STATUS})." >&2
    exit 1
  fi
  sleep 10
done

echo "=== [4/4] Verifying live HTTP 200 OK endpoints ==="
for ENDPOINT in "/healthz" "/" "/api/predictions"; do
  URL="${PUBLIC_URL}${ENDPOINT}"
  OK=0
  for TRY in 1 2 3 4 5 6; do
    HTTP_CODE="$(curl -sS -o /tmp/nhl_rlwy_check.out -w '%{http_code}' --max-time 25 "$URL" || echo "000")"
    if [ "$HTTP_CODE" = "200" ]; then
      BYTES="$(wc -c < /tmp/nhl_rlwy_check.out | tr -d ' ')"
      echo "  [200 OK] ${URL} (${BYTES} bytes)"
      OK=1
      break
    fi
    sleep 3
  done
  if [ "$OK" -ne 1 ]; then
    echo "ERROR: Endpoint ${URL} did not return 200 OK (last HTTP ${HTTP_CODE})." >&2
    exit 1
  fi
done
rm -f /tmp/nhl_rlwy_check.out

echo ""
echo "============================================================"
echo "LIVE RAILWAY URL: ${PUBLIC_URL}"
echo "HEALTHCHECK     : ${PUBLIC_URL}/healthz"
echo "============================================================"
