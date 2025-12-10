## Active Context

- **Current Focus**: Improving admin notifications for permission failures (Ban & Delete).
- **Key Decisions**:
  - **Ban Permission Checks**: Added `TelegramBadRequest` handling to `ban_user_for_spam`.
  - **Admin Notification**: If banning fails due to "not enough rights", admins now receive a specific alert (private -> group fallback) asking for 'Ban Users' permission.
  - **Consistency**: Matched logic with `handle_spam_message_deletion` for robust error handling.
  - **Centralized Logging**: Moved success/failure logging for admin notifications into `notify_admins_with_fallback_and_cleanup` to avoid code duplication in handlers.
  - **Guide Links**: Added `setup_guide_url` to both private and group permission failure notifications to help admins fix the issue immediately.
- **Recent Fixes**:
  - **Silent Failures Fixed**: Previously, failed bans were logged but admins were unaware. Now they get notified.
  - **Code Cleanup**: Removed redundant logging blocks from `handle_spam.py` after centralizing logic in `notifications.py`.
- **Immediate Next Steps**:
  - Verify logfire traces to ensure new notifications fire correctly.
  - Monitor for "cleaned up" groups where permissions are completely revoked.

- **Testing Status**: ✅ **Logic Implemented** - Added notifications for ban failures, centralized logging, and help links (including group fallbacks).
