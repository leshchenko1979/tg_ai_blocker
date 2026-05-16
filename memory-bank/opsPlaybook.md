# Ops playbook — agent pitfalls (learned in production)

Short reference for AI agents running deploys, migrations, broadcasts, and user-facing copy. Read with `techContext.md` and `activeContext.md`.

## Silent auto-delete (`delete_silent`)

- **No DM per deletion** — only high-confidence auto-delete confirmations are suppressed; low-confidence review and permission warnings still DM all admins.
- **Do not document “forward to bot to mark not spam” after silent auto-delete** — the message is already deleted in the group; there is nothing to forward. Normal auto-delete still sends a DM with **Not spam**; silent mode does not.
- **Group fallback** — if every admin is `delete_silent` and spam is auto-deleted, the bot must not post a public fallback in the group (implemented in `notify_admins`).

## Admin broadcast (`scripts/run_broadcast_on_vds.sh`)

| Pitfall | Symptom | Prevention |
|--------|---------|------------|
| **Stale resume file** | Log shows `Skipped (resume file): 250+`, `Successfully notified: 0–1` | New message/campaign → **`--new-campaign`** (clears container resume, does not upload local `broadcast_sent.ids`). Resume is per *campaign*, not global forever. |
| **Stale resume in container** | Same as above after local resume removed | `--new-campaign` runs `rm -f /app/scripts/broadcast_sent.ids` on the container before send. |
| **`docker cp` ownership** | `Permission denied: scripts/broadcast_sent.ids` after first send | `broadcast_remote.sh` runs `chown -R appuser:nogroup /app/scripts` as root after copy. |
| **False “success”** | `--min-sent 1` passes with 1 send and 252 skips | Wrapper checks log: if `Skipped (resume file)` ≫ `Successfully notified`, exit with error. `broadcast_updates.py` also errors when skip ratio is suspicious. |
| **Wrong audience file** | Dry-run count ≠ expectation | Export fresh IDs: `scripts/export_admin_ids.sh` (uses prod `PG_HOST=144.31.188.163` by default). |

**Recommended flow for a new announcement:** export IDs → dry-run → live with **`--new-campaign`** → confirm log `Successfully notified` ≈ recipient count minus deactivated accounts (~10).

## DB migrations from a Mac (local `uv run`)

- `.env` often has `PG_HOST=db` (Docker-only). **Override for prod:** `PG_HOST=144.31.188.163 uv run python -m src.migrations.migrate --flag`
- **Order:** expand migration → deploy app → smoke → comms → contract migration (`--drop-delete-spam` only after stable prod).

## Duplicate message handling

- **Edited messages causing duplicate inserts** — `insert_pending_spam_example` uses `ON CONFLICT (chat_id, message_id) WHERE confirmed = false DO UPDATE` to handle Telegram delivering both original + edited message updates for the same `(chat_id, message_id)`. The partial unique index `idx_spam_examples_pending_lookup` enforces uniqueness only for `confirmed=false` rows. Never remove this upsert pattern.

## User-facing copy (RU/EN)

- Avoid anglicisms in admin text: prefer «личное сообщение» / «уведомление в личку» (RU) or "private message" (EN), not «DM»; avoid «borderline» in channel posts.
- **Clarify "Not spam" button**: When describing auto-delete mode, always explain that the "Not spam" button is for fixing false positives (e.g., "на случай ошибки" or "to fix false positives").
- Cross-check help/locales/broadcast/channel post against **actual** behavior (especially silent mode and false-positive flows).
- Channel post: publish with **`parse_mode: html`** via Telegram MCP; save permalink for broadcast link.

## Comms order

1. Channel post @ai_antispam (public)
2. Admin broadcast with link to published post
3. Optional: landing news card update
