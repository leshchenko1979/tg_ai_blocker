#!/usr/bin/env bash
# Targeted admin broadcast inside tg-ai-blocker on the VDS (Docker image has no scripts/).
# Usage: ./scripts/run_broadcast_on_vds.sh [--dry-run] path/to/admin_ids.txt path/to/message.txt
# Requires: .env REMOTE_USER, REMOTE_HOST; SSH; container healthy.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

set -a
# shellcheck source=/dev/null
source "${ROOT}/.env"
set +a

: "${REMOTE_USER:?REMOTE_USER not set in .env}"
: "${REMOTE_HOST:?REMOTE_HOST not set in .env}"

DRY=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY=1
  shift
fi

IDS="${1:?Usage: $0 [--dry-run] admin_ids.txt message.txt}"
MSG="${2:?Usage: $0 [--dry-run] admin_ids.txt message.txt}"
[[ -f "$IDS" && -f "$MSG" ]] || { echo "Missing file(s)." >&2; exit 1; }

REMOTE_TMP="/tmp/tg_ai_broadcast_$$"

echo "==> Staging on ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_TMP}"
ssh -o BatchMode=yes "${REMOTE_USER}@${REMOTE_HOST}" "mkdir -p ${REMOTE_TMP}"
scp -q "${ROOT}/scripts/broadcast_updates.py" "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_TMP}/"
scp -q "$IDS" "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_TMP}/admin_ids.txt"
scp -q "$MSG" "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_TMP}/broadcast_message.txt"

echo "==> Running inside container tg-ai-blocker"
ssh -o BatchMode=yes "${REMOTE_USER}@${REMOTE_HOST}" bash -s "$REMOTE_TMP" "$DRY" <<'REMOTE_SCRIPT'
set -euo pipefail
RT="$1"
DR="$2"
cd /data/projects/tg-ai-blocker
docker compose exec -T tg-ai-blocker sh -c 'mkdir -p /app/scripts /app/src && (test -e /app/src/app || ln -snf /app/app /app/src/app) && (test -f /app/src/__init__.py || printf "" > /app/src/__init__.py)'
docker cp "${RT}/broadcast_updates.py" tg-ai-blocker:/app/scripts/broadcast_updates.py
docker cp "${RT}/admin_ids.txt" tg-ai-blocker:/app/scripts/admin_ids.txt
docker cp "${RT}/broadcast_message.txt" tg-ai-blocker:/app/scripts/broadcast_message.txt
if [[ "$DR" -eq 1 ]]; then
  docker compose exec -w /app -T tg-ai-blocker python scripts/broadcast_updates.py --dry-run --admin-ids-file scripts/admin_ids.txt
else
  docker compose exec -w /app -T tg-ai-blocker python scripts/broadcast_updates.py --admin-ids-file scripts/admin_ids.txt -f scripts/broadcast_message.txt
fi
rm -rf "${RT}"
REMOTE_SCRIPT

echo "==> Done."
