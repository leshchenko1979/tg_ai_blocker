import asyncio
import logging
from typing import Optional

import logfire

from .context_types import ContextResult, ContextStatus, UserContext
from .stories import collect_user_stories
from .user_profile import collect_user_context
from .user_context_utils import ensure_user_context_collectable

logger = logging.getLogger(__name__)


@logfire.instrument()
async def collect_complete_user_context(
    user_id: int,
    username: Optional[str] = None,
    chat_id: Optional[int] = None,
    message_id: Optional[int] = None,
    chat_username: Optional[str] = None,
) -> UserContext:
    """
    Collects complete user context including stories and profile info in parallel.
    Returns a UserContext with ContextResult objects for each context type.
    """
    with logfire.span(
        "Collecting complete user context",
        user_id=user_id,
        username=username,
        chat_id=chat_id,
    ):
        # Check if we need to subscribe user bot for context collection (when username is None)
        if username is None and chat_id is not None and message_id is not None:
            subscription_success = await ensure_user_context_collectable(
                chat_id, user_id, message_id, chat_username
            )
        else:
            subscription_success = (
                True  # No subscription needed if we have username or missing params
            )

        if not subscription_success:
            # Subscription failed, skip all context collection
            return UserContext(
                stories=ContextResult(
                    status=ContextStatus.SKIPPED, error="User bot subscription failed"
                ),
                linked_channel=ContextResult(
                    status=ContextStatus.SKIPPED, error="User bot subscription failed"
                ),
                account_info=ContextResult(
                    status=ContextStatus.SKIPPED, error="User bot subscription failed"
                ),
            )

        # Run stories and profile collection in parallel
        stories_task = collect_user_stories(user_id, username, chat_id)
        profile_task = collect_user_context(user_id, username, chat_id)

        try:
            results = await asyncio.gather(
                stories_task, profile_task, return_exceptions=True
            )
            stories_result = results[0]
            profile_result = results[1]

            # Handle stories result
            if isinstance(stories_result, Exception):
                logger.info(
                    "Failed to collect user stories",
                    extra={
                        "user_id": user_id,
                        "username": username,
                        "error": str(stories_result),
                    },
                )
                stories_context = ContextResult(
                    status=ContextStatus.FAILED, error=str(stories_result)
                )
            else:
                stories_context = stories_result

            # Handle profile result
            if isinstance(profile_result, Exception):
                logger.info(
                    "Failed to collect user profile context",
                    extra={
                        "user_id": user_id,
                        "username": username,
                        "error": str(profile_result),
                    },
                )
                # Create empty context with failed status
                profile_context = UserContext(
                    stories=ContextResult(
                        status=ContextStatus.FAILED, error=str(profile_result)
                    ),
                    linked_channel=ContextResult(
                        status=ContextStatus.FAILED, error=str(profile_result)
                    ),
                    account_info=ContextResult(
                        status=ContextStatus.FAILED, error=str(profile_result)
                    ),
                )
            else:
                profile_context = profile_result

            # Combine results into complete UserContext
            return UserContext(
                stories=stories_context,
                linked_channel=profile_context.linked_channel,
                account_info=profile_context.account_info,
            )

        except Exception as exc:
            # Fallback in case gather itself fails
            logger.info(
                "Failed to collect stories and profile data in parallel",
                extra={
                    "user_id": user_id,
                    "username": username,
                    "error": str(exc),
                },
            )
            return UserContext(
                stories=ContextResult(status=ContextStatus.FAILED, error=str(exc)),
                linked_channel=ContextResult(
                    status=ContextStatus.FAILED, error=str(exc)
                ),
                account_info=ContextResult(status=ContextStatus.FAILED, error=str(exc)),
            )
