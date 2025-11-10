## Tech Context

- **Language & Runtime**: Python 3.12+ (project typed for 3.13) running on macOS locally; production expects Linux with Telegram webhook hosting.
- **Frameworks & Libraries**:
  - `aiohttp` for webhook server, `aiogram` for Telegram bot routing.
  - `asyncpg` for PostgreSQL access, structured via database operation modules.
  - `python-dotenv` for configuration loading, `logfire` for tracing/logging, `mixpanel` for analytics, `tenacity` for retries.
- **Project Layout**: Source lives under `src/app`, grouped into `common`, `handlers`, `database`, plus `logging_setup.py`, `main.py`, and `server.py`. Tests mirror structure under `tests/` at project root using `pytest`.
- **Configuration**: Secrets pulled from `.env` (restricted). Startup script runs `dotenv.load_dotenv()` before initializing logging and handlers. Mixpanel tracking must respect admin-centric IDs per workspace rules.
- **Configuration Handling**: Secrets live in `.env`; contents remain off-limits, but developers can run `source .env` to load required environment variables without reading the file directly.
- **Infrastructure Assumptions**: Telegram webhook served over HTTPS (Traefik + Sablier managed), PostgreSQL reachable only via the remote host `94.250.254.232` using SSH (user `root`, DB user `postgres`). All database commands must execute on that server—local access is unavailable. Deployments rely on Docker Compose and require preserving `.env` and `docker-compose.yml`.
- **Tooling**: Formatting enforced via project conventions; prefer ASCII. Testing through `pytest`. Use `python3`/`pip3` and `zsh` per environment note.
- **Tooling**:
  - Formatting enforced via project conventions; prefer ASCII. Testing through `pytest`. Use `python3`/`pip3` and `zsh` per environment note.
  - `deploy_scalene.sh` spins up the Scalene-instrumented stack (Dockerfile.scalene + docker-compose.scalene.yml) under `/data/projects/tg-ai-blocker-scalene`, capturing reports in `profiles/` (Scalene runs with `--html --json --outfile /app/profiles/scalene_report`). VS Code task `Deploy Scalene Profiling` runs the script locally.
- **Error Notification**: `TelegramLogHandler` uses a queue-based approach with background task to send WARNING+ level logs to admin chat. Includes throttling (10/min) and deduplication (15s). ERROR/CRITICAL messages bypass throttling but retain deduplication to ensure critical errors are notified while preventing spam.
- **Linked Channel Testing Infrastructure**: Comprehensive test suite in `tests/common/test_linked_channel.py` with CSV-driven test cases (`tests/linked_channel_test.csv`) validates bot vs MTProto extraction methods. Includes SSL bypass for local MTProto testing and detailed success/failure matrix analysis. Bot extraction tested for both user info access and channel info access separately.


