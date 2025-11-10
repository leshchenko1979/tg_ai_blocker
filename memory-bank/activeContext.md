## Active Context

- **Current Focus**: Reinforce comment moderation and classification by enriching LLM prompts with MTProto-derived channel snapshots and explicit suspicion heuristics.
- **Key Decisions**:
  - Build an `MtprotoHttpClient` wrapper that reads credentials from `MTPROTO_HTTP_BEARER_TOKEN` and defaults to `https://tg-mcp.redevest.ru`.
  - Collect channel metadata (title, username, invite link, subscriber count, post range, latest post preview) via `account.getProfilePeer`, `channels.getFullChannel`, and `messages.getHistory` only for threaded comment messages.
  - Treat linked channels with subscribers < 10, posts < 50, and age_delta < 10 months as suspicious within the classifier prompt.
  - Allow logging setup to skip Logfire when `SKIP_LOGFIRE` is set or pytest is detected so local testing keeps stdout logs and avoids init failures.
- **Immediate Next Steps**:
  - Execute `tests/common/test_linked_channel.py` to compare bot vs MTProto extraction methods and determine if MTProto fallback adds value.
  - Based on test results, decide whether to keep or remove MTProto fallback from `collect_linked_channel_summary`.
  - Monitor telemetry for MTProto bridge failures, prompt drift, and the new suspicion rule; adjust retry/backoff if needed.
  - Confirm `.env` contains the required `MTPROTO_HTTP_BEARER_TOKEN` and optionally override base URL when deploying outside prod bridge.
  - Re-run regression tests covering spam classification once classifier prompt adjustments stabilize, including cases with linked channels near the thresholds.
- **Testing Status**: ✅ **COMPREHENSIVE TESTING INFRASTRUCTURE IMPLEMENTED** - Created `tests/common/test_linked_channel.py` with full comparison testing for bot vs MTProto extraction. Test loads CSV data (`tests/linked_channel_test.csv`), tests both extraction methods, compares results, and provides formatted console output with recommendations. Ready to execute and analyze results to determine MTProto fallback value.


