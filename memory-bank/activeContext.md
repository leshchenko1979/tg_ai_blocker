## Active Context

- **Current Focus**: Reinforce comment moderation by enriching LLM context with MTProto-derived data about user-linked channels.
- **Key Decisions**:
  - Build an `MtprotoHttpClient` wrapper that reads credentials from `MTPROTO_HTTP_BEARER_TOKEN` and defaults to `https://tg-mcp.redevest.ru`.
  - Collect channel metadata (title, username, invite link, subscriber count, post range, latest post preview) via `account.getProfilePeer`, `channels.getFullChannel`, and `messages.getHistory` only for threaded comment messages.
- **Immediate Next Steps**:
  - Monitor telemetry for MTProto bridge failures and adjust retry/backoff if needed.
  - Confirm `.env` contains the required `MTPROTO_HTTP_BEARER_TOKEN` and optionally override base URL when deploying outside prod bridge.
  - Re-run regression tests covering spam classification once classifier prompt adjustments stabilize.


