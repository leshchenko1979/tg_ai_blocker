#!/usr/bin/env bash
# Export active administrator Telegram IDs to scripts/admin_ids.txt (gitignored).
# Default PG_HOST is production VDS IP — override if needed.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
OUT="${ROOT}/scripts/admin_ids.txt"

set -a
# shellcheck source=/dev/null
source "${ROOT}/.env"
set +a

export PG_HOST="${PG_HOST:-144.31.188.163}"

uv run python <<PY
import asyncio
from dotenv import load_dotenv

load_dotenv()
from src.app.database.postgres_connection import get_pool, close_pool
from src.app.database.admin_operations import get_all_admins

OUT = "${OUT}"

async def main():
    await get_pool()
    admins = await get_all_admins()
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("# active administrators (is_active=TRUE)\n")
        for a in admins:
            f.write(f"{a.admin_id}\n")
    print(f"Wrote {len(admins)} IDs to {OUT}")
    await close_pool()

asyncio.run(main())
PY
