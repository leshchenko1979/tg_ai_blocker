"""
Message processing submodule.

This module contains the core message processing functionality split into:
- pipeline: Core moderation pipeline
- validation: Message validation and filtering
- channel_management: Channel and discussion group handling
"""

from .channel_management import (
    build_channel_instruction_message,
    get_discussion_username,
    handle_channel_post,
    notify_channel_admins,
    notify_channel_admins_and_leave,
)
from .pipeline import (
    handle_moderated_message,
    process_spam_or_approve,
)
from .validation import (
    check_known_member,
    check_skip_channel_bot_message,
    determine_effective_user_id,
    fetch_linked_chat_id,
    get_and_check_group,
    is_admin_posting_as_group,
    is_channel_bot_in_discussion,
    should_attempt_api_fetch,
    validate_group_and_check_early_exits,
)

__all__ = [
    # Channel management
    "build_channel_instruction_message",
    "get_discussion_username",
    "handle_channel_post",
    "notify_channel_admins",
    "notify_channel_admins_and_leave",
    # Pipeline
    "handle_moderated_message",
    "process_spam_or_approve",
    # Validation
    "check_known_member",
    "check_skip_channel_bot_message",
    "determine_effective_user_id",
    "fetch_linked_chat_id",
    "get_and_check_group",
    "is_admin_posting_as_group",
    "is_channel_bot_in_discussion",
    "should_attempt_api_fetch",
    "validate_group_and_check_early_exits",
]
