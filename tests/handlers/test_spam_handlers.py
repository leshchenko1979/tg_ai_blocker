import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.exceptions import TelegramBadRequest

from src.app.handlers.handle_spam import handle_spam_message_deletion


class MockTelegramBadRequest(TelegramBadRequest):
    """Mock TelegramBadRequest for testing."""

    def __init__(self, message):
        # TelegramBadRequest requires method and message, but we can mock it
        super().__init__(MagicMock(), message)


class TestSpamDeletion:
    """Test spam message deletion and permission error handling."""

    @pytest.fixture
    def mock_message(self):
        """Create a mock message for testing."""
        message = MagicMock()
        message.message_id = 12345
        message.chat.id = -1001234567890
        message.chat.title = "Test Group"

        user = MagicMock()
        user.id = 67890
        user.full_name = "Test User"
        user.username = "testuser"
        message.from_user = user

        return message

    @pytest.mark.asyncio
    async def test_successful_spam_deletion(self, mock_message):
        """Test successful spam message deletion."""
        with (
            patch("src.app.handlers.handle_spam.bot") as mock_bot,
            patch("src.app.handlers.handle_spam.track_group_event") as mock_track,
        ):
            mock_bot.delete_message = AsyncMock()

            await handle_spam_message_deletion(mock_message)

            mock_bot.delete_message.assert_called_once_with(
                mock_message.chat.id, mock_message.message_id
            )
            mock_track.assert_called_once()

    @pytest.mark.asyncio
    async def test_spam_deletion_non_permission_error(self, mock_message):
        """Test spam deletion failure due to non-permission error."""
        with (
            patch("src.app.handlers.handle_spam.bot") as mock_bot,
            patch("src.app.handlers.handle_spam.track_group_event") as mock_track,
            patch("src.app.handlers.handle_spam.logger") as mock_logger,
        ):
            mock_bot.delete_message = AsyncMock(
                side_effect=MockTelegramBadRequest("Some other error")
            )

            await handle_spam_message_deletion(mock_message)

            mock_bot.delete_message.assert_called_once_with(
                mock_message.chat.id, mock_message.message_id
            )
            # Should log the error and track failure, but not notify admins
            assert mock_logger.warning.called
            mock_track.assert_called_once()

    @pytest.mark.asyncio
    async def test_spam_deletion_permission_error_admin_notification_success(
        self, mock_message
    ):
        """Test spam deletion failure due to permission error with successful admin notification."""
        with (
            patch("src.app.handlers.handle_spam.bot") as mock_bot,
            patch("src.app.handlers.handle_spam.get_group") as mock_get_group,
            patch(
                "src.app.handlers.handle_spam.notify_admins_with_fallback_and_cleanup"
            ) as mock_notify,
            patch("src.app.handlers.handle_spam.track_group_event") as mock_track,
            patch("src.app.handlers.handle_spam.logger") as mock_logger,
        ):
            # Mock permission error
            permission_error = MockTelegramBadRequest(
                "Not enough rights to delete message"
            )
            mock_bot.delete_message = AsyncMock(side_effect=permission_error)

            # Mock group data
            mock_group = MagicMock()
            mock_group.admin_ids = [111, 222]
            mock_get_group.return_value = mock_group

            # Mock successful notification
            mock_notify.return_value = {
                "notified_private": [111],
                "group_notified": False,
            }

            await handle_spam_message_deletion(mock_message)

            mock_bot.delete_message.assert_called_once_with(
                mock_message.chat.id, mock_message.message_id
            )

            # Should get group info
            mock_get_group.assert_called_once_with(mock_message.chat.id)

            # Should notify admins about missing rights
            mock_notify.assert_called_once()
            call_args, call_kwargs = mock_notify.call_args
            # call_args[0] is bot, call_args[1] is admin_ids, call_args[2] is group_id
            assert call_args[1] == [111, 222]  # admin_ids
            assert call_args[2] == mock_message.chat.id  # group_id
            assert (
                "У меня нет права удалять спам-сообщения"
                in call_kwargs["private_message"]
            )

            # Should track failure
            mock_track.assert_called_once()

    @pytest.mark.asyncio
    async def test_spam_deletion_permission_error_notification_failure(
        self, mock_message
    ):
        """Test spam deletion failure due to permission error with failed admin notification."""
        with (
            patch("src.app.handlers.handle_spam.bot") as mock_bot,
            patch("src.app.handlers.handle_spam.get_group") as mock_get_group,
            patch(
                "src.app.handlers.handle_spam.notify_admins_with_fallback_and_cleanup"
            ) as mock_notify,
            patch("src.app.handlers.handle_spam.track_group_event") as mock_track,
            patch("src.app.handlers.handle_spam.logger") as mock_logger,
        ):
            # Mock permission error
            permission_error = MockTelegramBadRequest(
                "Need administrator rights to delete messages"
            )
            mock_bot.delete_message = AsyncMock(side_effect=permission_error)

            # Mock group data
            mock_group = MagicMock()
            mock_group.admin_ids = [111, 222]
            mock_get_group.return_value = mock_group

            # Mock notification failure that triggers cleanup
            mock_notify.side_effect = Exception("All notification methods failed")

            await handle_spam_message_deletion(mock_message)

            mock_bot.delete_message.assert_called_once_with(
                mock_message.chat.id, mock_message.message_id
            )

            # Should attempt to notify admins
            mock_notify.assert_called_once()

            # Should log the notification failure
            warning_calls = [
                call
                for call in mock_logger.warning.call_args_list
                if "Failed to notify admins about missing rights" in str(call)
            ]
            assert len(warning_calls) == 1

            # Should track failure
            mock_track.assert_called_once()

    @pytest.mark.asyncio
    async def test_spam_deletion_permission_error_no_group(self, mock_message):
        """Test spam deletion failure due to permission error when group not found."""
        with (
            patch("src.app.handlers.handle_spam.bot") as mock_bot,
            patch("src.app.handlers.handle_spam.get_group") as mock_get_group,
            patch(
                "src.app.handlers.handle_spam.notify_admins_with_fallback_and_cleanup"
            ) as mock_notify,
            patch("src.app.handlers.handle_spam.track_group_event") as mock_track,
            patch("src.app.handlers.handle_spam.logger") as mock_logger,
        ):
            # Mock permission error
            permission_error = MockTelegramBadRequest("Chat admin required")
            mock_bot.delete_message = AsyncMock(side_effect=permission_error)

            # Mock group not found
            mock_get_group.return_value = None

            await handle_spam_message_deletion(mock_message)

            mock_bot.delete_message.assert_called_once_with(
                mock_message.chat.id, mock_message.message_id
            )

            # Should not attempt to notify admins if group not found
            mock_notify.assert_not_called()

            # Should track failure
            mock_track.assert_called_once()
