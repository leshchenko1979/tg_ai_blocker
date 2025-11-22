## Active Context

- **Current Focus**: Monitor Logfire performance with newly fixed metrics and complete any remaining admin message formatting.
- **Key Decisions**:
  - Build an `MtprotoHttpClient` wrapper that reads credentials from `MTPROTO_HTTP_BEARER_TOKEN` and defaults to `https://tg-mcp.redevest.ru`.
  - Collect channel metadata (title, username, invite link, subscriber count, post range, latest post preview) via `account.getProfilePeer`, `channels.getFullChannel`, and `messages.getHistory` only for threaded comment messages.
  - Treat linked channels with subscribers < 10, posts < 50, and age_delta < 10 months as suspicious within the classifier prompt.
  - Allow logging setup to skip Logfire when `SKIP_LOGFIRE` is set or pytest is detected so local testing keeps stdout logs and avoids init failures.
  - Implemented Logfire client-based message lookup scoped to admin-managed chats for reliable spam message deletion, now supports hidden user forwards.
  - Unified permission failure handling: When bot lacks delete rights for spam/service messages ("message can't be deleted" or permission errors), notify admins with private→group fallback and leave group/clean DB if all notification methods fail.
  - HTML formatting migration completed for all user-facing messages: private AI responses, command replies, and notifications now use consistent HTML formatting.
  - AI prompts updated with HTML formatting instructions to ensure consistent styling in AI-generated responses.
  - Help message restructured with progressive disclosure: main help now shows concise overview with inline keyboard buttons for detailed sections (getting started, training, moderation rules, commands, payment, support).
  - Logfire metrics fixed: All metrics (histograms and gauges) now initialized once at module level to prevent null values in metric tables. Server `serve_time_histogram` and spam classifier `spam_score_gauge`/`attempts_histogram` follow this pattern.
  - Fixed critical bug where channel spam messages were approving the generic "Channel Bot" ID (136817688), whitelisting all future channel spam. Implemented logic to use `sender_chat.id` as the effective user ID for moderation and cleaned up erroneous approvals.

- **Immediate Next Steps**:
  - Execute `tests/common/test_linked_channel.py` to compare bot vs MTProto extraction methods and determine if MTProto fallback adds value.
  - Based on test results, decide whether to keep or remove MTProto fallback from `collect_linked_channel_summary`.
  - Monitor telemetry for Logfire lookup success rates, MtProto bridge failures, prompt drift, and the new suspicion rule; adjust retry/backoff if needed. Verify Logfire metrics are now recording correctly without null values.
  - Confirm `.env` contains the required `LOGFIRE_READ_TOKEN` and `MTPROTO_HTTP_BEARER_TOKEN` and optionally override base URL when deploying outside prod bridge.
  - Complete HTML migration for remaining admin-only messages (server error notifications).
  - Re-run regression tests covering spam classification once classifier prompt adjustments stabilize, including cases with linked channels near the thresholds.
- **Testing Status**: ✅ **COMPREHENSIVE TESTING INFRASTRUCTURE IMPLEMENTED** - Created `tests/common/test_linked_channel.py` with full comparison testing for bot vs MTProto extraction. Test loads CSV data (`tests/linked_channel_test.csv`), tests both extraction methods, compares results, and provides formatted console output with recommendations. Ready to execute and analyze results to determine MTProto fallback value. ✅ **LOGFIRE LOOKUP TESTING IMPLEMENTED** - Added `tests/handlers/test_private_handlers.py` with comprehensive tests for Logfire message lookup integration. ✅ **PERMISSION FAILURE TESTING IMPLEMENTED** - Added comprehensive tests for spam deletion permission errors and notification cleanup flows in `tests/handlers/test_spam_handlers.py` and `tests/common/test_notifications.py`.
