"""Unit tests for no-rights grace period jobs."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.background_jobs.no_rights import leave_no_rights_groups


@pytest.mark.asyncio
async def test_leave_no_rights_groups_clears_flag_when_rights_restored():
    """When bot has rights, clear_no_rights_detected_at is called and no leave."""

    class FakeAdminWithRights:
        can_delete_messages = True
        can_restrict_members = True

    with (
        patch("app.background_jobs.no_rights.load_config") as mock_load,
        patch(
            "app.background_jobs.no_rights.get_groups_with_no_rights_past_grace"
        ) as mock_get,
        patch("app.background_jobs.no_rights.bot") as mock_bot,
        patch(
            "app.background_jobs.no_rights.ChatMemberAdministrator",
            FakeAdminWithRights,
        ),
        patch(
            "app.background_jobs.no_rights.clear_no_rights_detected_at",
            new_callable=AsyncMock,
        ) as mock_clear,
        patch(
            "app.background_jobs.no_rights.perform_complete_group_cleanup",
            new_callable=AsyncMock,
        ) as mock_cleanup,
    ):
        mock_load.return_value = {"billing": {"no_rights_grace_days": 7}}
        mock_get.return_value = [100]
        mock_bot.me = AsyncMock(return_value=MagicMock(id=999))

        admin_member = FakeAdminWithRights()
        mock_bot.get_chat_member = AsyncMock(return_value=admin_member)

        await leave_no_rights_groups()

        mock_clear.assert_called_once_with(100)
        mock_cleanup.assert_not_called()


@pytest.mark.asyncio
async def test_leave_no_rights_groups_leaves_when_no_rights():
    """When bot has no rights, perform_complete_group_cleanup is called."""
    with (
        patch("app.background_jobs.no_rights.load_config") as mock_load,
        patch(
            "app.background_jobs.no_rights.get_groups_with_no_rights_past_grace"
        ) as mock_get,
        patch("app.background_jobs.no_rights.bot") as mock_bot,
        patch(
            "app.background_jobs.no_rights.get_group", new_callable=AsyncMock
        ) as mock_get_group,
        patch(
            "app.background_jobs.no_rights.perform_complete_group_cleanup",
            new_callable=AsyncMock,
        ) as mock_cleanup,
        patch(
            "app.background_jobs.no_rights._send_admin_message",
            new_callable=AsyncMock,
        ) as mock_send,
    ):
        mock_load.return_value = {"billing": {"no_rights_grace_days": 7}}
        mock_get.return_value = [100]
        mock_bot.me = AsyncMock(return_value=MagicMock(id=999, username="test_bot"))
        mock_bot.get_chat = AsyncMock(
            return_value=MagicMock(title="Test Group", username="test")
        )

        member_mock = MagicMock()
        member_mock.can_delete_messages = False
        member_mock.can_restrict_members = False
        mock_bot.get_chat_member = AsyncMock(return_value=member_mock)

        from app.database.models import Group

        mock_get_group.return_value = Group(
            group_id=100,
            admin_ids=[111],
            moderation_enabled=True,
            member_ids=[],
            created_at=datetime.now(timezone.utc),
            last_updated=datetime.now(timezone.utc),
        )

        mock_cleanup.return_value = True

        await leave_no_rights_groups()

        mock_cleanup.assert_called_once_with(100)
        mock_send.assert_called_once()
        assert "Test Group" in str(mock_send.call_args) or "100" in str(
            mock_send.call_args
        )


@pytest.mark.asyncio
async def test_leave_no_rights_groups_empty_list_returns_early():
    """When no groups past grace, returns without API calls."""
    with (
        patch("app.background_jobs.no_rights.load_config") as mock_load,
        patch(
            "app.background_jobs.no_rights.get_groups_with_no_rights_past_grace"
        ) as mock_get,
        patch("app.background_jobs.no_rights.bot") as mock_bot,
        patch(
            "app.background_jobs.no_rights.perform_complete_group_cleanup",
            new_callable=AsyncMock,
        ) as mock_cleanup,
    ):
        mock_load.return_value = {"billing": {"no_rights_grace_days": 7}}
        mock_get.return_value = []

        await leave_no_rights_groups()

        mock_cleanup.assert_not_called()
        mock_bot.me.assert_not_called()
