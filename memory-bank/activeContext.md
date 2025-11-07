## Active Context

- **Current Focus**: Align critical warnings and errors with the Python logging pipeline so the Telegram escalation handler captures them while retaining logfire spans/metrics for observability.
- **Key Decisions**:
  - Refactored `common.llms` and `common.spam_classifier` to use module loggers for warning/error reporting, preserving existing logfire instrumentation where it adds trace data.
  - Keep logfire metric gauges in the spam classifier to monitor scoring attempts without duplicating alert noise.
- **Immediate Next Steps**:
  - Monitor Telegram alert volume and adjust handler throttling if noise becomes excessive.
  - Watch for new logfire error/warning usage in future changes and migrate them to logging promptly.
  - Confirm production environments have the required dependencies (`mixpanel`, `asyncpg`) installed after local test runs.

