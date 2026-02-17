"""
Trace context utilities for storing and retrieving the root span.

OpenTelemetry does not provide an API to walk from the current span to the root.
We store the root span in the trace context when it is created (in main.py)
and retrieve it downstream via get_root_span(). The context propagates through
async/await automatically.
"""

from typing import Any

from opentelemetry import context
from opentelemetry.trace import Span, get_current_span

ROOT_SPAN_KEY = context.create_key("logfire_root_span")


def set_root_span(span: Any) -> None:
    """
    Store the root span in the current context so it can be retrieved downstream.
    Call this when entering the root span (e.g., in the update handler).
    """
    ctx = context.get_current()
    ctx = context.set_value(ROOT_SPAN_KEY, span, ctx)
    context.attach(ctx)


def get_root_span() -> Span:
    """
    Get the root span from the current context, if one was stored via set_root_span().
    Falls back to the current span when the root span is not set.
    """
    span = context.get_value(ROOT_SPAN_KEY)
    if span is not None and hasattr(span, "set_attribute"):
        return span  # type: ignore[return-value]
    return get_current_span()
