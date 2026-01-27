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
- **Testing Infrastructure**: ✅ **Complete** - Proper separation of unit tests (93) from integration tests. pytest.ini addopts correctly excludes integration tests from deployment. All integration tests properly marked with `@pytest.mark.integration`.
- **Documentation**: ✅ **Updated PRD** - `PRD.md` synchronized with codebase and memory bank.
- **MTProto Optimization**: ✅ **Peer Resolution Optimized** - Eliminated 90%+ failing numeric ID calls by requiring username-only resolution.
- **Logfire Message Lookup**: ✅ **Integration Test Created** - Added `test_logfire_message_lookup.py` that proves the system can successfully recover forwarded channel messages from Logfire traces, even when forward metadata extraction fails initially.
- Hidden User ID Recovery
- **Edited Message Handling**: ✅ **Added Handler for Edited Messages** - Edited messages now return "edited_message_ignored" tag instead of generic "unhandled" for better Logfire observability. Handler does nothing else - edited messages are not moderated.
    - **Landing Page**: ✅ **Complete** - Professional Russian landing page with Tailwind CSS, real spam examples, FAQ, strong CTA, optimized styling, improved accessibility, and automated CI/CD deployment to GitHub Pages. Explicitly emphasizes Telegram spam protection.
- **Handler Return Values**: ✅ **Fixed** - All Telegram update handlers now return descriptive strings instead of None, preventing "_ignored" tags in logfire traces. Fixed payment handlers (`handle_buy_command`, `handle_buy_stars_callback`, `process_pre_checkout_query`, `process_successful_payment`) and command handlers (`cmd_ref`).
- **Enhanced Spam Examples Context Storage**: ✅ **Complete** - Added `stories_context`, `reply_context`, `account_age_context` fields to spam examples database with three-state differentiation (NULL for historical, '[EMPTY]' for checked-but-empty, content for found). Logfire trace recovery enables context extraction from forwarded messages. Examples now include full classification context for improved LLM training effectiveness.
- **LLM Model Evaluation Infrastructure**: ✅ **Complete** - Comprehensive evaluation script (`scripts/eval_llm_models.py`) with balanced test cases, hierarchical tqdm progress bars, JSON results storage, model isolation, and detailed accuracy metrics (precision, recall, F1). Includes automatic result persistence to `eval_results/` directory and git exclusion.
- **Code Architecture & Quality**: ✅ **Complete** - Comprehensive module reorganization moving spam detection logic to dedicated `src/app/spam/` directory. Implemented robust context collection architecture with `ContextResult` wrapper and clear status contracts. Achieved significant code quality improvements with systematic linting cleanup (74→57 errors), ruff linting compliance, and all tests passing. **MTProto Peer Context Establishment**: ✅ **Documented** - Comprehensive documentation of the peer resolution preparation process with clear strategies for different message types.
- **Advanced Context Collection**: ✅ **Complete** - On-demand user bot subscription system enables comprehensive spam detection for all users, regardless of username availability. Unified subscription logic with DRY helpers, simplified MTProto calls, and merged utility modules for clean architecture. **Optimized Discussion Thread Context**: ✅ **Complete** - Smart peer resolution that skips subscription for discussion threads (may be private) and uses thread-based reading only via `messages.getReplies` for maximum efficiency. **Forum vs Discussion Distinction**: ✅ **Complete** - Correctly distinguishes between forum topic messages (`is_topic_message: true`) and discussion thread messages using the Telegram Bot API `is_topic_message` field. **Universal Message Object Optimization**: ✅ **Complete** - All context collection functions now accept either full message objects or individual parameters, eliminating redundant field extraction and maintaining backward compatibility across different calling contexts (message processing, callbacks, forwarded messages). **Channel-Linked Discussion Thread Resolution**: ✅ **Complete** - Enhanced peer resolution for discussion groups linked to channels now reads from the **public channel** instead of potentially private discussion groups, using original channel post IDs extracted from forwarded messages (`forward_from_message_id`) for optimal MTProto peer resolution.

### What's left to build
- [ ] Comprehensive "shadow mode" for testing new classifiers without affecting users.
- [ ] Advanced billing dashboard for admins.
- [ ] More granular spam categories in reporting.
- [ ] Subscription status caching to reduce MTProto API calls.

### Known Issues
- [ ] `TelegramBadRequest` for "message to delete not found" can still be noisy in logs (harmless race condition).
- [x] **Fixed**: User bot subscription now properly skips private chats (without usernames) and continues with context collection if user bot already has access.
- [x] **Fixed**: HTML parsing errors in admin notifications due to unescaped HTML entities in chat titles and user names (causing "Unsupported start tag" Telegram API errors).
