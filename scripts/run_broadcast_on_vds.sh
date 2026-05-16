#!/usr/bin/env bash
# Targeted admin broadcast inside ai-antispam on the VDS (Docker image has no scripts/).
# Usage:
#   ./scripts/run_broadcast_on_vds.sh [--dry-run] [--new-campaign] admin_ids.txt message.txt
# --new-campaign: do not upload local broadcast_sent.ids; clear container resume (new message).
# Requires: .env REMOTE_USER, REMOTE_HOST; SSH; container healthy.
# Live runs log to broadcast_last_run.log and fetch scripts/broadcast_sent.ids from the container.
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
NEW_CAMPAIGN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY=1; shift ;;
    --new-campaign) NEW_CAMPAIGN=1; shift ;;
    -*) echo "Unknown option: $1" >&2; exit 1 ;;
    *) break ;;
  esac
done

IDS="${1:?Usage: $0 [--dry-run] [--new-campaign] admin_ids.txt message.txt}"
MSG="${2:?Usage: $0 [--dry-run] [--new-campaign] admin_ids.txt message.txt}"
[[ -f "$IDS" && -f "$MSG" ]] || { echo "Missing file(s)." >&2; exit 1; }

LOG_FILE="${ROOT}/broadcast_last_run.log"
REMOTE_TMP="/tmp/tg_ai_broadcast_$$"
RESUME_LOCAL="${ROOT}/scripts/broadcast_sent.ids"

echo "==> Staging on ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_TMP}"
ssh -o BatchMode=yes "${REMOTE_USER}@${REMOTE_HOST}" "mkdir -p ${REMOTE_TMP}"
scp "${ROOT}/scripts/broadcast_updates.py" "${ROOT}/scripts/broadcast_remote.sh" \
  "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_TMP}/"
scp "$IDS" "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_TMP}/admin_ids.txt"
scp "$MSG" "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_TMP}/broadcast_message.txt"

if [[ "$NEW_CAMPAIGN" -eq 1 ]]; then
  echo "==> New campaign: not uploading local resume (will clear on container)"
elif [[ -f "$RESUME_LOCAL" ]]; then
  echo "==> Uploading local resume file (scripts/broadcast_sent.ids) — omit --new-campaign only to resume same message"
  scp "$RESUME_LOCAL" "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_TMP}/broadcast_sent.ids"
fi

echo "==> Running inside container ai-antispam (log: ${LOG_FILE})"
START_SEC=$SECONDS

set +e
ssh -o BatchMode=yes "${REMOTE_USER}@${REMOTE_HOST}" \
  "NEW_CAMPAIGN=${NEW_CAMPAIGN} bash ${REMOTE_TMP}/broadcast_remote.sh ${REMOTE_TMP} ${DRY}" 2>&1 | tee "$LOG_FILE"
EXEC_EXIT=${PIPESTATUS[0]}
set -e

ELAPSED=$((SECONDS - START_SEC))
echo "==> Elapsed: ${ELAPSED}s"

if [[ "$EXEC_EXIT" -ne 0 ]]; then
  echo "ERROR: Remote broadcast failed (exit ${EXEC_EXIT}). See ${LOG_FILE}." >&2
  exit "$EXEC_EXIT"
fi

if [[ "$DRY" -eq 1 ]]; then
  if ! grep -q 'Dry run:' "$LOG_FILE"; then
    echo "ERROR: No dry-run output in log. Broadcast may not have run. See ${LOG_FILE}." >&2
    exit 1
  fi
else
  if ! grep -q 'Successfully notified:' "$LOG_FILE"; then
    echo "ERROR: No broadcast summary in log — run failed or sent nothing. See ${LOG_FILE}." >&2
    exit 1
  fi

  SENT_LINE=$(grep 'Successfully notified:' "$LOG_FILE" | tail -1 || true)
  SKIPPED_LINE=$(grep 'Skipped (resume file):' "$LOG_FILE" | tail -1 || true)
  if [[ -n "$SENT_LINE" && -n "$SKIPPED_LINE" ]]; then
    SENT=$(echo "$SENT_LINE" | grep -oE '[0-9]+$' || echo 0)
    SKIPPED=$(echo "$SKIPPED_LINE" | grep -oE '[0-9]+$' || echo 0)
    if [[ "$SKIPPED" -gt 50 && "$SENT" -lt 10 ]]; then
      echo "ERROR: Only ${SENT} sent but ${SKIPPED} skipped (stale resume?). Re-run with --new-campaign. See ${LOG_FILE}." >&2
      exit 1
    fi
  fi

  RESUME_REMOTE="/tmp/tg_ai_broadcast_resume_$$"
  echo "==> Fetching resume file from container"
  if ssh -o BatchMode=yes "${REMOTE_USER}@${REMOTE_HOST}" \
    "docker cp ai-antispam:/app/scripts/broadcast_sent.ids ${RESUME_REMOTE} 2>/dev/null"; then
    scp "${REMOTE_USER}@${REMOTE_HOST}:${RESUME_REMOTE}" "$RESUME_LOCAL"
    ssh -o BatchMode=yes "${REMOTE_USER}@${REMOTE_HOST}" "rm -f ${RESUME_REMOTE}"
  else
    echo "WARN: No broadcast_sent.ids in container yet (first run or none sent)." >&2
  fi
fi

echo "==> Done."
