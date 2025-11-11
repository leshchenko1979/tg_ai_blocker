import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.app.common.notifications import notify_admins_with_fallback_and_cleanup


class TestNotifyAdminsWithCleanup:
    """Test admin notification with cleanup behavior."""

    @pytest.fixture
    def mock_bot(self):
        """Create a mock bot for testing."""
        bot = MagicMock()
        bot.get_chat = AsyncMock()
        bot.send_message = AsyncMock()
        bot.leave_chat = AsyncMock()
        return bot

    @pytest.mark.asyncio
    async def test_cleanup_leaves_group_and_cleans_db(self, mock_bot):
        """Test that cleanup leaves the group and cleans database when notifications fail."""
        admin_ids = [111, 222]
        group_id = -1001234567890

        # Mock all notification methods to fail
        mock_bot.get_chat.side_effect = Exception("Cannot reach admin")
        mock_bot.send_message.side_effect = Exception("Cannot send message")

        with (
            patch("src.app.common.notifications.get_pool") as mock_get_pool,
            patch(
                "src.app.common.notifications.cleanup_inaccessible_group"
            ) as mock_cleanup,
            patch("src.app.common.notifications.logger") as mock_logger,
        ):
            # Mock database connection
            mock_pool = MagicMock()
            mock_conn = MagicMock()
            mock_pool.acquire.return_value.__aenter__ = AsyncMock(
                return_value=mock_conn
            )
            mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_get_pool.return_value = mock_pool

            result = await notify_admins_with_fallback_and_cleanup(
                mock_bot,
                admin_ids,
                group_id,
                "Test message",
                cleanup_if_group_fails=True,
            )

            # Should attempt to get admin chats (twice per admin due to retry fallback)
            assert mock_bot.get_chat.call_count == len(admin_ids) * 2

            # Should leave the group
            mock_bot.leave_chat.assert_called_once_with(group_id)

            # Should clean up database
            mock_cleanup.assert_called_once_with(mock_conn, group_id)

            # Should return cleanup result
            assert result["group_cleaned_up"] is True
            assert result["notified_private"] == []
            assert result["group_notified"] is False

    @pytest.mark.asyncio
    async def test_no_cleanup_when_private_notification_succeeds(self, mock_bot):
        """Test that cleanup is not triggered when private notifications succeed."""
        admin_ids = [111]
        group_id = -1001234567890

        # Mock successful private notification
        mock_chat = MagicMock()
        mock_bot.get_chat.return_value = mock_chat
        mock_bot.send_message.return_value = MagicMock()

        result = await notify_admins_with_fallback_and_cleanup(
            mock_bot, admin_ids, group_id, "Test message", cleanup_if_group_fails=True
        )

        # Should not leave group or clean database
        mock_bot.leave_chat.assert_not_called()

        # Should return success result
        assert result["group_cleaned_up"] is False
        assert result["notified_private"] == [111]
        assert result["group_notified"] is False

    @pytest.mark.asyncio
    async def test_no_cleanup_when_cleanup_disabled(self, mock_bot):
        """Test that cleanup is not triggered when cleanup_if_group_fails=False."""
        admin_ids = [111, 222]
        group_id = -1001234567890

        # Mock all notification methods to fail
        mock_bot.get_chat.side_effect = Exception("Cannot reach admin")
        mock_bot.send_message.side_effect = Exception("Cannot send message")

        with (
            patch("src.app.common.notifications.get_pool") as mock_get_pool,
            patch(
                "src.app.common.notifications.cleanup_inaccessible_group"
            ) as mock_cleanup,
        ):
            result = await notify_admins_with_fallback_and_cleanup(
                mock_bot,
                admin_ids,
                group_id,
                "Test message",
                cleanup_if_group_fails=False,  # Disabled
            )

            # Should not leave group or clean database
            mock_bot.leave_chat.assert_not_called()
            mock_get_pool.assert_not_called()
            mock_cleanup.assert_not_called()

            # Should return no cleanup result
            assert result["group_cleaned_up"] is False
