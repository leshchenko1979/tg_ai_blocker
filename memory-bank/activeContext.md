## Active Context

- **Current Focus**: User experience improved with safer defaults for new users.
- **Key Decisions**:
  - **Safer Default Mode**: New users now start in notification mode (delete_spam=False) instead of automatic deletion mode to prevent false positives and user abandonment.
- **Improved Onboarding**:
  - Spam notifications now include helpful guidance about using /mode command to switch to deletion mode.
  - Instructions for granting admin rights are now context-aware (Bot is Admin vs Bot is NOT Admin) and cross-platform friendly.
  - Config help text updated to match the official guide for adding administrators.
- **Performance Optimization**: Implemented `assume_human_admins` parameter to skip expensive API calls for pre-filtered admin lists (~50-80% performance improvement).
- **Bot Admin Filtering**: Robust bot detection prevents GroupAnonymousBot and other bot accounts from blocking admin notifications.
- **Enhanced Logging**:
  - Comprehensive logging for bot removal events with automatic Logfire instrumentation.
  - `my_chat_member` updates now properly return "bot_status_updated" to populate Logfire span tags correctly.
  - **Optimization**: `my_chat_member` updates from private chats (user block/unblock) are now ignored to prevent log noise and unnecessary processing.
- **Architecture Cleanup**: Separated concerns between database operations and business logic, eliminated duplicate cleanup functions.
  - **Database Security**: Bot filtering at database level in stored procedure prevents future contamination.

- **Immediate Next Steps**:
  - Monitor user adoption and feedback on the new notification-first approach.
  - Track conversion rates from notification mode to deletion mode.
  - Verify continued reliability of admin notifications when bot gets kicked.

- **Testing Status**: ✅ **USER EXPERIENCE IMPROVED** - All tests pass, new default behavior implemented, notification guidance added.
