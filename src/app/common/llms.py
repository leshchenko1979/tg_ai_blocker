"""pydantic-ai migration: raw LLM HTTP client removed.

All LLM calls are now routed through pydantic-ai agents in agents.py.
This module provides a no-op stub for close_llm_http_resources to avoid
import errors during transition.
"""

import logging

logger = logging.getLogger(__name__)


async def close_llm_http_resources() -> None:
    """No-op stub — pydantic-ai manages its own transport lifecycle."""
    pass
