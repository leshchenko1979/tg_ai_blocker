# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ai-antispam** — Telegram AI spam blocker bot using LLMs for classification.

- Bot: [@ai_spam_blocker_bot](https://t.me/ai_spam_blocker_bot)
- Channel: [@ai_antispam](https://t.me/ai_antispam)
- Site: [ai-antispam.ru](https://ai-antispam.ru)

## Commands

```bash
# Install dependencies
uv sync

# Run tests
pytest tests/ -v

# Lint & format
ruff check src/ tests/
ruff format src/ tests/

# Type check
uvx ty check src

# Run locally (from project dir)
python -m src.app.main
```

## Architecture

```
src/app/
├── main.py           # Entry point
├── bot_commands.py   # Telegram bot commands
├── handlers/         # Message/event handlers
├── spam/             # Spam detection logic
├── database/          # DB queries and models
├── background_jobs/  # Async tasks
├── common/           # Shared utilities
├── types.py          # Pydantic types
├── i18n.py           # Internationalization
└── locales/          # Translation files
```

## Database

**DBHub MCP** connected to PostgreSQL at `144.31.188.163:5432/ai_spam_bot`.

## MCP Servers

- **DBHub**: PostgreSQL database access
- **Context7**: API documentation
- **logfire**: Logs and metrics
- **MiniMax**: Coding plan MCP
- **telegram**: Telegram bot integration

## Memory Bank

At start of dialog, read relevant memory-bank files:
- `memory-bank/activeContext.md` — current system state
- `memory-bank/confirmedSpamExamples.md` — labeled spam examples
- `memory-bank/progress.md` — recent work log
- `memory-bank/techContext.md` — technical details

## Key Patterns

- Spam classification uses LLM with confidence thresholds (default 90%)
- Admin can set auto-delete mode or notification-only mode
- Billing via Telegram Stars
- Personal spam examples per admin for fine-tuning
