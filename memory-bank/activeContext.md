## Active Context

- **Current Focus**: Implement protection against profile-based spam attacks (Stories) by fetching and analyzing user stories during spam classification.
- **Key Decisions**:
  - Build an `MtprotoHttpClient` wrapper that reads credentials from `MTPROTO_HTTP_BEARER_TOKEN` and defaults to `https://tg-mcp.redevest.ru`.
  - Collect channel metadata via MTProto for threaded comment messages.
  - **New Feature**: Implemented story-based spam detection. The bot now collects user stories via MTProto `stories.getPinnedStories` ONLY.
  - **Investigation Finding**: Spam attacks rely on pinned stories in profiles. Regular `stories.getPeerStories` is noisy or empty for non-contacts. We now exclusively check `stories.getPinnedStories` to catch the "Trojan horse" profile attack.
  - **Classifier Update**: Updated system prompt to treat suspicious content in stories (links, crypto scams, "check profile" calls) as high-confidence spam indicators, even if the message text is benign.
  - Treat linked channels with subscribers < 10, posts < 50, and age_delta < 10 months as suspicious.
  - Allow logging setup to skip Logfire when `SKIP_LOGFIRE` is set or pytest is detected.
  - Unified permission failure handling for spam/service message deletion.
  - HTML formatting migration completed for all user-facing messages.
  - Logfire metrics initialized at module level to prevent null values.
  - Fixed channel bot approval bug by using `sender_chat.id` as effective user ID.
  - Replaced local `stats` table with direct Logfire queries.

- **Immediate Next Steps**:
  - Monitor effectiveness of story-based spam detection in production; watch for false positives if users have benign links in stories.
  - Execute `tests/common/test_linked_channel.py` to compare bot vs MTProto extraction methods.
  - Monitor telemetry for Logfire lookup success rates and MtProto bridge failures.
  - Confirm `.env` contains the required `LOGFIRE_READ_TOKEN` and `MTPROTO_HTTP_BEARER_TOKEN`.

- **Testing Status**: ✅ **STORY SPAM DETECTION TESTED** - Implemented `tests/common/test_stories.py` verifying story collection and formatting, specifically targeting **pinned stories only**. Updated `tests/common/test_spam_classifier.py` to verify prompt generation with story context. All regression tests passed. ✅ **COMPREHENSIVE TESTING INFRASTRUCTURE** - Full test suite covers linked channels, Logfire lookups, permission failures, and callback handlers.
