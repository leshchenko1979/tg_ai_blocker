## Tech Context

- **Language & Runtime**: Python 3.12+ (project typed for 3.13) running on macOS locally; production expects Linux with Telegram webhook hosting.
- **Frameworks & Libraries**:
  - `aiohttp` for webhook server, `aiogram` for Telegram bot routing.
  - `asyncpg` for PostgreSQL access, structured via database operation modules.
  - `python-dotenv` for configuration loading, `logfire` for tracing/logging, `mixpanel` for analytics, `tenacity` for retries.
- **Project Layout**: Source lives under `src/app`, grouped into `common`, `handlers`, `database`, plus `logging_setup.py`, `main.py`, and `server.py`. Tests mirror structure under `src/tests` using `pytest`.
- **Configuration**: Secrets pulled from `.env` (restricted). Startup script runs `dotenv.load_dotenv()` before initializing logging and handlers. Mixpanel tracking must respect admin-centric IDs per workspace rules.
- **Infrastructure Assumptions**: Telegram webhook served over HTTPS (Traefik + Sablier managed), PostgreSQL available via remote host `94.250.254.232` with `postgres` user. Deployments rely on Docker Compose and require preserving `.env` and `docker-compose.yml`.
- **Tooling**: Formatting enforced via project conventions; prefer ASCII. Testing through `pytest`. Use `python3`/`pip3` and `zsh` per environment note.


