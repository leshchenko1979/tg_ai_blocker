import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.exceptions import TelegramBadRequest

from src.app.handlers.handle_spam import handle_spam_message_deletion
from src.app.spam.message_context import get_spam_score_and_bio
from src.app.spam.context_types import (
    SpamClassificationContext,
    ContextResult,
    ContextStatus,
    LinkedChannelSummary,
)


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
        message.sender_chat = None  # Default to no sender_chat

        return message

    @pytest.mark.asyncio
    async def test_successful_spam_deletion(self, mock_message):
        """Test successful spam message deletion."""
        with (
            patch("src.app.handlers.handle_spam.bot") as mock_bot,
            patch("src.app.handlers.handle_spam.track_group_event") as mock_track,
        ):
            mock_bot.delete_message = AsyncMock()

            await handle_spam_message_deletion(mock_message, [123456789])

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

            await handle_spam_message_deletion(mock_message, [123456789])

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
            patch(
                "src.app.handlers.handle_spam.notify_admins_with_fallback_and_cleanup"
            ) as mock_notify,
            patch("src.app.handlers.handle_spam.track_group_event") as mock_track,
        ):
            # Mock permission error
            permission_error = MockTelegramBadRequest(
                "Not enough rights to delete message"
            )
            mock_bot.delete_message = AsyncMock(side_effect=permission_error)

            # Mock successful notification
            mock_notify.return_value = {
                "notified_private": [111],
                "group_notified": False,
            }

            await handle_spam_message_deletion(mock_message, [111, 222])

            mock_bot.delete_message.assert_called_once_with(
                mock_message.chat.id, mock_message.message_id
            )

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

            # Mock notification failure that triggers cleanup
            mock_notify.side_effect = Exception("All notification methods failed")

            await handle_spam_message_deletion(mock_message, [111, 222])

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
            patch(
                "src.app.handlers.handle_spam.notify_admins_with_fallback_and_cleanup"
            ) as mock_notify,
            patch("src.app.handlers.handle_spam.track_group_event") as mock_track,
        ):
            # Mock permission error
            permission_error = MockTelegramBadRequest("Chat admin required")
            mock_bot.delete_message = AsyncMock(side_effect=permission_error)

            # Simulate no admins available
            await handle_spam_message_deletion(mock_message, [])

            mock_bot.delete_message.assert_called_once_with(
                mock_message.chat.id, mock_message.message_id
            )

            # Should not attempt to notify admins if group not found
            mock_notify.assert_not_called()

            # Should track failure
            mock_track.assert_called_once()

    @pytest.mark.asyncio
    async def test_sender_chat_spam_check_trigger(self, mock_message):
        """
        Test that messages with sender_chat trigger collect_channel_summary_by_id
        and the result is passed to is_spam.
        """
        # Setup mock message with sender_chat
        mock_message.sender_chat = MagicMock()
        mock_message.sender_chat.id = -1002916411724  # Example channel ID
        mock_message.sender_chat.title = "Channel Bot"
        mock_message.sender_chat.type = "channel"
        mock_message.chat.id = -1001503592176  # Different group ID
        mock_message.reply_to_message = None  # No reply in this test

        # Mock group
        mock_group = MagicMock()
        mock_group.admin_ids = [123]

        with (
            patch(
                "src.app.spam.message_context.is_spam", new_callable=AsyncMock
            ) as mock_is_spam,
            patch("src.app.common.bot.bot") as mock_bot,
            patch(
                "src.app.common.mtproto_client.MtprotoHttpClient.call",
                new_callable=AsyncMock,
            ) as mock_mtproto_call,
        ):
            mock_is_spam.return_value = (
                85,
                "Test spam reason",
            )  # Spam score and reason

            # Mock get_chat to return an object with description = None
            mock_chat_info = MagicMock()
            mock_chat_info.description = None
            mock_bot.get_chat = AsyncMock(return_value=mock_chat_info)

            # Mock MTProto client call to prevent HTTP requests
            mock_mtproto_call.return_value = {
                "subscribers": 150,
                "total_posts": 25,
                "post_age_delta": 2,
                "recent_posts": ["Test post content"]
            }

            await get_spam_score_and_bio(
                mock_message, "test message", mock_group, False
            )

            # Verify MTProto call was made (indicating channel context collection)
            assert mock_mtproto_call.called

            # Verify is_spam was called with proper context
            mock_is_spam.assert_called_once()
            kwargs = mock_is_spam.call_args[1]
            context = kwargs["context"]
            assert context.name == "Channel Bot"  # sender_chat.title
            # Bio comes from message.chat.description (mock object in test)
            assert (
                context.linked_channel is not None
            )  # Channels now get linked channel analysis
            assert context.linked_channel.status == ContextStatus.FOUND
            assert context.stories is None  # No stories collection for channels
            assert context.reply is None  # No reply in this test
