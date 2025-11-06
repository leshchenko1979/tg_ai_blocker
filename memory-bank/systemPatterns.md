## System Patterns

- **Runtime Architecture**: `aiohttp` web application exposes Telegram webhook endpoint, forwards updates to a shared `aiogram` dispatcher hosted in `src/app/handlers`. Execution wrapped with `logfire` spans for observability and guarded by timeout/error helpers.
- **Bot Composition**:
  - `src/app/common` encapsulates integrations: Telegram bot client, LLM providers, Mixpanel tracking, notifications, shared utilities, and spam classifier logic.
  - Handlers under `src/app/handlers` are organized by intent (callbacks, commands, payments, spam handling) and register with the dispatcher via side effects on import.
- **Data Access Layer**: `src/app/database` offers explicit operation modules (admins, groups, messages, spam examples) built atop a PostgreSQL connection helper, keeping SQL isolated from business logic.
- **Spam Decision Flow**: Updates route through filters that skip admins/service messages, score content via classifier and custom examples, execute moderation actions (delete/ban/release), and log outcomes to Mixpanel and Logfire.
- **Billing & Credits**: Telegram Stars payments handled by dedicated handlers coupled with database operations that maintain balances, histories, and automatic moderation toggles when credits drop.
- **Configuration & Startup**: `.env` loaded in `src/app/main.py`, logging initialized before dispatcher registration. Web app run via `aiohttp.web`. Tests rely on `pytest` with fixtures under `src/tests` mirroring production modules.


