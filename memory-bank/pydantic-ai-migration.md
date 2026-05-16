# pydantic-ai Migration (2026-04-21)

## What Was Done

Replaced raw aiohttp/httpx LLM integration with pydantic-ai agents for both spam classification and admin chat.

## Key Files

### New: `src/app/agents.py`
- `SpamClassification` Pydantic model (structured output: `is_spam`, `confidence`, `reason`)
- Gateway spam agent: `get_gateway_spam_agent()` — custom AI Gateway, single model
- OpenRouter spam agent pool: `get_openrouter_spam_agent()` — round-robin across 6 models from `config.yaml` `llm.openrouter_models` (mirrors gateway route ai-antispam)
- Chat agent: `get_chat_agent()` — gateway first, plain text output
- Retry via `AsyncTenacityTransport` with 5 attempts, `wait_retry_after`; timeouts from `llm.route_timeout_seconds` (30) and `llm.http_client_timeout_seconds` (60)
- Webhook LLM fallback: `has_time_for_llm_attempt` (min 3s to start) + `effective_llm_request_timeout` (cap per call to remaining − 2s buffer)
- **Bug fixed**: base URLs already include `/v1`, so code used `.rstrip('/')` (NOT `+ '/v1'`) to avoid double `/v1/v1`

### `src/app/spam/spam_classifier.py`
- Gateway first → OpenRouter pool with rotation on failure
- `agent.run(user_message, instructions=system_prompt)` — pydantic-ai 1.84.1 uses `instructions=`, not `system_prompt=`
- Structured output: `result.output.is_spam/confidence/reason` — no JSON parsing needed
- Removed broken `@logfire.instrument(extract_args=True, record_return=True)` decorator
- Explicit `logfire.span()` for gateway call, failure, and openrouter loop

### `src/app/common/llms.py`
- Reduced to no-op stub for `close_llm_http_resources()`
- All raw HTTP client code removed

### `src/app/spam/llm_client.py`
- Metrics only (`classification_confidence_gauge`, `attempts_histogram`)
- All JSON/legacy parsing removed

### `src/app/handlers/private_handlers.py`
- `get_llm_response_with_fallback` → `get_chat_agent().run()`
- History passed as formatted string in user message (not message list)

### `src/app/main.py`
- Custom `RateLimitExceeded`/`LocationNotSupported` → pydantic-ai `ModelAPIError`/`ModelHTTPError`
- `is_rate_limit = status_code == 429`
- `setup_logging(environment="production")`

### `src/app/logging_setup.py`
- `_reset_debug()` — resets `debug` flag before re-enabling Logfire for integration tests
- `setup_logging(environment=...)` — environment parameter for isolation
- `send_to_logfire="if-token-present"` — **critical**: overrides pytest's default `False` that blocks cloud export
- `logfire.instrument_pydantic_ai()` — traces pydantic-ai agent runs (includes token usage in Chat Completion spans)
- `"app.agents"` added to `install_auto_tracing` modules

### `tests/conftest.py`
- `SKIP_LOGFIRE=1` set as default before any imports (prevents Logfire init during collection)
- `pytest_collection_finish`: detects integration tests → calls `_reset_debug()` + `setup_logging(environment="testing")`
- `pytest_sessionfinish`: resets state, calls `mute_logging_for_tests()`

### `tests/integration/test_spam_classifier.py`
- Added `test_spam_classifier_direct()` — calls `is_spam()` directly without channel fetch

## Running Integration Tests

```bash
# Default: unit tests only (SKIP_LOGFIRE=1, no Logfire)
uv run python -m pytest tests/ -v

# Integration tests: must use --override-ini="addopts=" to override pytest.ini's -m "not integration"
uv run python -m pytest tests/integration/ -v -m integration --override-ini="addopts="

# With --logfire flag: activates logfire pytest plugin (affects console output format)
uv run python -m pytest tests/integration/ -v -m integration --override-ini="addopts=" --logfire

# Run specific test with output
uv run python -m pytest tests/integration/test_spam_classifier.py::test_spam_classifier_direct -v -m integration --override-ini="addopts=" --logfire -s
```

## Logfire Trace Chain (confirmed visible in cloud)

```
pytest: ai-antispam (root)
  test_spam_classifier_direct
    spam_classifier_gateway_call
      agent run (pydantic-ai)
        chat ai-antispam (pydantic-ai)
          Chat Completion with 'ai-antispam' [LLM] (openai)
```

## Key Lessons

1. **Double /v1/v1 URL bug**: `API_BASE=https://ai-gateway.l1979.ru/v1` already includes `/v1`. Appending another `/v1` in code → 404. Fix: `.rstrip('/')` only.
2. **pytest default blocks Logfire**: `send_to_logfire=False` by default in pytest. Must override with `send_to_logfire="if-token-present"`.
3. **PYTEST_CURRENT_TEST env var**: pytest sets this, causing `_should_skip_logfire()` to return True. Must `os.environ.pop()` in `pytest_collection_finish`.
4. **`debug` flag persists**: `mute_logging_for_tests()` sets `debug=True` globally, which persists across tests. Must reset with `_reset_debug()` before `setup_logging()`.
5. **`@logfire.instrument` fails in pytest**: `InspectArgumentsFailedWarning` and `TypeError: 'LogfireSpan' object is not callable` — avoid decorators, use explicit `with logfire.span()`.
6. **pydantic-ai uses OpenAI client**: internally uses `openai` Python package, not httpx directly. `instrument_pydantic_ai()` alone provides Chat Completion spans with token usage; `instrument_openai()` is redundant.
7. **API_BASE from .env**: `https://ai-gateway.l1979.ru/v1` — gateway works with MiniMax-M2.7 model.
