"""Tests for trusted-member early exit in message validation."""

import pytest
from unittest.mock import AsyncMock, patch

from src.app.handlers.message.validation import validate_group_and_check_early_exits


@pytest.mark.asyncio
async def test_probation_member_not_skipped():
    group_id = -100123
    user_id = 456
    mock_group = type(
        "Group",
        (),
        {"admin_ids": [999], "moderation_enabled": True},
    )()

    with (
        patch(
            "src.app.handlers.message.validation.get_and_check_group",
            new_callable=AsyncMock,
            return_value=(mock_group, ""),
        ),
        patch(
            "src.app.handlers.message.validation.is_trusted_member",
            new_callable=AsyncMock,
            return_value=False,
        ),
    ):
        group, reason = await validate_group_and_check_early_exits(group_id, user_id)
        assert group is mock_group
        assert reason == ""


@pytest.mark.asyncio
async def test_trusted_member_skipped():
    group_id = -100123
    user_id = 456
    mock_group = type(
        "Group",
        (),
        {"admin_ids": [999], "moderation_enabled": True},
    )()

    with (
        patch(
            "src.app.handlers.message.validation.get_and_check_group",
            new_callable=AsyncMock,
            return_value=(mock_group, ""),
        ),
        patch(
            "src.app.handlers.message.validation.is_trusted_member",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        _, reason = await validate_group_and_check_early_exits(group_id, user_id)
        assert reason == "message_trusted_member_skipped"
