#!/usr/bin/env bash
# Runs on the VDS host (not inside the container). Invoked by run_broadcast_on_vds.sh.
set -euo pipefail

RT="${1:?staging dir}"
DR="${2:?0|1}"
NEW_CAMPAIGN="${NEW_CAMPAIGN:-0}"

echo "==> Remote broadcast start (dry_run=${DR}, new_campaign=${NEW_CAMPAIGN})"
cd /data/projects/ai-antispam

docker compose exec -T ai-antispam sh -c \
  'mkdir -p /app/scripts /app/src && (test -e /app/src/app || ln -snf /app/app /app/src/app) && (test -f /app/src/__init__.py || printf "" > /app/src/__init__.py)'

docker cp "${RT}/broadcast_updates.py" ai-antispam:/app/scripts/broadcast_updates.py
docker cp "${RT}/admin_ids.txt" ai-antispam:/app/scripts/admin_ids.txt
docker cp "${RT}/broadcast_message.txt" ai-antispam:/app/scripts/broadcast_message.txt
if [[ "${NEW_CAMPAIGN}" -eq 1 ]]; then
  echo "==> New campaign: clearing container resume file"
  docker exec ai-antispam rm -f /app/scripts/broadcast_sent.ids 2>/dev/null || true
elif [[ -f "${RT}/broadcast_sent.ids" ]]; then
  docker cp "${RT}/broadcast_sent.ids" ai-antispam:/app/scripts/broadcast_sent.ids
fi
# docker cp leaves root-owned files; app runs as appuser and must append resume IDs
docker exec -u root ai-antispam chown -R appuser:nogroup /app/scripts 2>/dev/null || true

docker compose exec -w /app -T ai-antispam test -f scripts/broadcast_updates.py
docker compose exec -w /app -T ai-antispam test -f scripts/admin_ids.txt

if [[ "$DR" -eq 1 ]]; then
  docker compose exec -w /app -T ai-antispam python -u scripts/broadcast_updates.py \
    --dry-run --admin-ids-file scripts/admin_ids.txt
else
  CLEAR_ARGS=()
  if [[ "${NEW_CAMPAIGN}" -eq 1 ]]; then
    CLEAR_ARGS=(--clear-resume)
  fi
  docker compose exec -w /app -T ai-antispam python -u scripts/broadcast_updates.py \
    --admin-ids-file scripts/admin_ids.txt \
    -f scripts/broadcast_message.txt \
    --parse-mode HTML \
    --resume-file scripts/broadcast_sent.ids \
    "${CLEAR_ARGS[@]}" \
    --min-sent 1
fi

echo "==> Remote broadcast finished"
rm -rf "${RT}"
