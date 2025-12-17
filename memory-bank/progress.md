## Progress

### What works
- Telegram webhook server
- aiogram handlers
- Spam classifier (LLM + Context + Stories + Account Age)
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
- Linked Channel detection (Username-first resolution)
- Logfire message lookup
- Hidden User ID Recovery

### What's left to build
- [ ] Comprehensive "shadow mode" for testing new classifiers without affecting users.
- [ ] Advanced billing dashboard for admins.
- [ ] More granular spam categories in reporting.

### Known Issues
- [ ] `TelegramBadRequest` for "message to delete not found" can still be noisy in logs (harmless race condition).
- [x] **Fixed**: HTML parsing errors in admin notifications due to unescaped HTML entities in chat titles and user names (causing "Unsupported start tag" Telegram API errors).
