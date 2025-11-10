---
## Progress

- **Functional**: Telegram webhook server, aiogram handlers, spam classifier, billing via Telegram Stars, Mixpanel tracking hooks, PostgreSQL data layer, MTProto bridge enrichment, Telegram logging handler (with logfire spans), and a `/health` endpoint returning plain `ok` for Sablier probes are live; comment-spam prompt now interprets linked-channel fragments with explicit suspicion thresholds. Linked channel extraction optimized with username-first resolution (tries username before user ID) and direct MTProto-only approach (bot API calls removed). Logfire client-based message lookup implemented for reliable spam deletion from forwarded reports, scoped to admin-managed chats with 3-day search window. A Scalene profiling stack can be deployed via `deploy_scalene.sh` (Dockerfile.scalene + docker-compose.scalene.yml) to investigate memory usage, storing reports under `profiles/`.
---

