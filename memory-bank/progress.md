## Progress

### What works
- Telegram webhook server
- aiogram handlers
- Spam classifier (LLM + Context + Stories + Account Age + Discussion Context with relevance evaluation)
- Billing via Telegram Stars
- Mixpanel tracking
- PostgreSQL data layer
- MTProto bridge
- Telegram logging handler
- **Robust Permission Handling**:
  - Message deletion permission checks.
  - **User ban permission checks** (New: notifies admins if ban fails).
- Admin Notifications:
  - Private chat priority
  - Group chat fallback
  - Automatic cleanup if unreachable
  - **Collapsed Quote Formatting**: Both cited message and reason now display as collapsed blockquotes for better readability
- Linked Channel detection (Username-first resolution)
- **Enhanced Channel Content Analysis**: ✅ **Tested & Working** - Now fetches and analyzes text content from recent posts, not just metadata (successfully detects porn/spam channels by content)
- **Spam Example Curation**: ✅ **Database Optimized** - Promoted 15 high-quality patterns to common, deduplicated 14 redundant entries from the baseline, and cleaned up top 2 admins. Baseline now provides high-quality starting point with balanced scores.
- **Testing Infrastructure**: ✅ **Complete** - Proper separation of unit tests (83) from integration tests. Deployment runs only reliable unit tests.
- **Documentation**: ✅ **Updated PRD** - `PRD.md` synchronized with codebase and memory bank.
- **MTProto Optimization**: ✅ **Peer Resolution Optimized** - Eliminated 90%+ failing numeric ID calls by requiring username-only resolution.
- **Logfire Message Lookup**: ✅ **Integration Test Created** - Added `test_logfire_message_lookup.py` that proves the system can successfully recover forwarded channel messages from Logfire traces, even when forward metadata extraction fails initially.
- Hidden User ID Recovery
- **Edited Message Handling**: ✅ **Added Handler for Edited Messages** - Edited messages now return "edited_message_ignored" tag instead of generic "unhandled" for better Logfire observability. Handler does nothing else - edited messages are not moderated.
    - **Landing Page**: ✅ **Complete** - Professional Russian landing page with Tailwind CSS, real spam examples, FAQ, strong CTA, optimized styling, improved accessibility, and automated CI/CD deployment to GitHub Pages. Explicitly emphasizes Telegram spam protection.

### What's left to build
- [ ] Comprehensive "shadow mode" for testing new classifiers without affecting users.
- [ ] Advanced billing dashboard for admins.
- [ ] More granular spam categories in reporting.

### Known Issues
- [ ] `TelegramBadRequest` for "message to delete not found" can still be noisy in logs (harmless race condition).
- [x] **Fixed**: HTML parsing errors in admin notifications due to unescaped HTML entities in chat titles and user names (causing "Unsupported start tag" Telegram API errors).
