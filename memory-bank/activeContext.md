## Active Context

- **Current Focus**: Reinforce comment moderation and classification by enriching LLM prompts with MTProto-derived channel snapshots and explicit suspicion heuristics.
- **Key Decisions**:
  - Build an `MtprotoHttpClient` wrapper that reads credentials from `MTPROTO_HTTP_BEARER_TOKEN` and defaults to `https://tg-mcp.redevest.ru`.
  - Collect channel metadata (title, username, invite link, subscriber count, post range, latest post preview) via `account.getProfilePeer`, `channels.getFullChannel`, and `messages.getHistory` only for threaded comment messages.
  - Treat linked channels with subscribers < 10, posts < 50, and age_delta < 10 months as suspicious within the classifier prompt.
- **Immediate Next Steps**:
  - Monitor telemetry for MTProto bridge failures, prompt drift, and the new suspicion rule; adjust retry/backoff if needed.
  - Confirm `.env` contains the required `MTPROTO_HTTP_BEARER_TOKEN` and optionally override base URL when deploying outside prod bridge.
  - Re-run regression tests covering spam classification once classifier prompt adjustments stabilize, including cases with linked channels near the thresholds.


