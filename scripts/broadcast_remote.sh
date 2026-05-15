#!/usr/bin/env bash
# Runs on the VDS host (not inside the container). Invoked by run_broadcast_on_vds.sh.
set -euo pipefail

RT="${1:?staging dir}"
DR="${2:?0|1}"

echo "==> Remote broadcast start (dry_run=${DR})"
cd /data/projects/ai-antispam

docker compose exec -T ai-antispam sh -c \
  'mkdir -p /app/scripts /app/src && (test -e /app/src/app || ln -snf /app/app /app/src/app) && (test -f /app/src/__init__.py || printf "" > /app/src/__init__.py)'

docker cp "${RT}/broadcast_updates.py" ai-antispam:/app/scripts/broadcast_updates.py
docker cp "${RT}/admin_ids.txt" ai-antispam:/app/scripts/admin_ids.txt
docker cp "${RT}/broadcast_message.txt" ai-antispam:/app/scripts/broadcast_message.txt
if [[ -f "${RT}/broadcast_sent.ids" ]]; then
  docker cp "${RT}/broadcast_sent.ids" ai-antispam:/app/scripts/broadcast_sent.ids
fi

docker compose exec -w /app -T ai-antispam test -f scripts/broadcast_updates.py
docker compose exec -w /app -T ai-antispam test -f scripts/admin_ids.txt

if [[ "$DR" -eq 1 ]]; then
  docker compose exec -w /app -T ai-antispam python -u scripts/broadcast_updates.py \
    --dry-run --admin-ids-file scripts/admin_ids.txt
else
  docker compose exec -w /app -T ai-antispam python -u scripts/broadcast_updates.py \
    --admin-ids-file scripts/admin_ids.txt \
    -f scripts/broadcast_message.txt \
    --parse-mode HTML \
    --resume-file scripts/broadcast_sent.ids \
    --min-sent 1
fi

echo "==> Remote broadcast finished"
rm -rf "${RT}"
