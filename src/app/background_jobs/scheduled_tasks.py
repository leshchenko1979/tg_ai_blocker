"""
Unified scheduled jobs: low balance warnings, cache cleanups.

Runs daily. Replaces the former low_balance_loop with a single loop that:
1. Sends low balance / depletion timeline notifications
2. Cleans message_lookup_cache (7 days TTL)
3. Cleans message_history (24h TTL)
4. Cleans pending spam_examples (3 days TTL)
"""

import asyncio
import logging

from .low_balance import run_low_balance_checks
from .no_rights import leave_no_rights_groups
from ..database.message_lookup import cleanup_old_lookup_entries
from ..database.message_operations import cleanup_old_message_history
from ..database.spam_examples import cleanup_pending_spam_examples

logger = logging.getLogger(__name__)

SECONDS_PER_DAY = 86400


async def run_scheduled_jobs() -> None:
    """Run all scheduled jobs: low balance checks and cache cleanups."""
    try:
        await run_low_balance_checks()
    except Exception as e:
        logger.error(f"Low balance checks failed: {e}", exc_info=True)

    try:
        await leave_no_rights_groups()
    except Exception as e:
        logger.error(f"No-rights group leave failed: {e}", exc_info=True)

    try:
        await cleanup_old_lookup_entries(days=7)
    except Exception as e:
        logger.error(f"message_lookup_cache cleanup failed: {e}", exc_info=True)

    try:
        await cleanup_old_message_history()
    except Exception as e:
        logger.error(f"message_history cleanup failed: {e}", exc_info=True)

    try:
        await cleanup_pending_spam_examples()
    except Exception as e:
        logger.error(f"pending spam_examples cleanup failed: {e}", exc_info=True)


async def scheduled_jobs_loop() -> None:
    """Background loop: run jobs every 24 hours. Cancel on shutdown."""
    while True:
        try:
            await run_scheduled_jobs()
        except asyncio.CancelledError:
            logger.info("Scheduled jobs loop cancelled")
            raise
        except Exception as e:
            logger.error(f"Scheduled jobs loop error: {e}", exc_info=True)
        await asyncio.sleep(SECONDS_PER_DAY)
