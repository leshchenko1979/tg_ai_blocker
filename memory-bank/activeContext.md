## Active Context

- **Current Focus**: Fix issue where channel info extraction failed for channel senders (sender_chat) by enabling username-based resolution.
- **Key Decisions**:
  - `collect_channel_summary_by_id` now accepts an optional `username` parameter.
  - It attempts to resolve the channel via username first, then falls back to ID. This matches the behavior of `collect_linked_channel_summary` and improves reliability for channels not yet seen by the MTProto bridge.
  - Updated `message_handlers.py` to pass `sender_chat.username` when collecting stats for channel senders.
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
  - Monitor production logs to confirm channel extraction failures (ValueError: Could not find the input entity) decrease.
  - Monitor effectiveness of story-based spam detection.
  - Confirm `.env` contains the required `LOGFIRE_READ_TOKEN` and `MTPROTO_HTTP_BEARER_TOKEN`.

- **Testing Status**: ✅ **CHANNEL EXTRACTION FIXED** - Updated `collect_channel_summary_by_id` and added tests in `tests/common/test_linked_channel.py`. ✅ **STORY SPAM DETECTION TESTED** - Implemented `tests/common/test_stories.py`. All regression tests passed.
