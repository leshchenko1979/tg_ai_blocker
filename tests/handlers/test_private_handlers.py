import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from aiogram import types

from src.app.handlers.private_handlers import extract_original_message_info


class TestExtractOriginalMessageInfo:
    """Test the extract_original_message_info function with Logfire lookup integration."""

    @pytest.fixture
    def mock_callback_message(self):
        """Create a mock callback message with a forwarded message."""
        # Create mock forwarded message
        forwarded_message = MagicMock(spec=types.Message)
        forwarded_message.text = "Test spam message"
        forwarded_message.caption = None
        forwarded_message.forward_date = datetime.now(timezone.utc)
        forwarded_message.date = datetime.now(timezone.utc)

        # Mock forward origin (user type)
        origin = MagicMock(spec=types.MessageOriginUser)
        origin.type = "user"
        sender_user = MagicMock(spec=types.User)
        sender_user.id = 12345
        sender_user.full_name = "Spammer User"
        sender_user.username = "spammeruser"
        origin.sender_user = sender_user
        forwarded_message.forward_origin = origin
        forwarded_message.forward_from = None

        # Create mock callback message
        callback_message = MagicMock(spec=types.Message)
        callback_message.reply_to_message = forwarded_message

        return callback_message

    @pytest.fixture
    def mock_bot_get_chat(self):
        """Mock bot.get_chat for user bio retrieval."""
        with patch("src.app.handlers.private_handlers.bot") as mock_bot:
            mock_chat = MagicMock()
            mock_chat.bio = "Spammer bio"
            mock_bot.get_chat = AsyncMock(return_value=mock_chat)
            yield mock_bot

    @pytest.mark.asyncio
    async def test_logfire_lookup_success(
        self, mock_callback_message, mock_bot_get_chat
    ):
        """Test successful Logfire lookup when forward metadata lacks group info."""
        admin_id = 99999

        # Mock admin groups
        with patch(
            "src.app.handlers.private_handlers.get_admin_groups", new_callable=AsyncMock
        ) as mock_get_groups:
            mock_get_groups.return_value = [{"id": 1001}, {"id": 1002}, {"id": 1003}]

            # Mock successful Logfire lookup
            with patch(
                "src.app.handlers.private_handlers.find_original_message",
                new_callable=AsyncMock,
            ) as mock_lookup:
                mock_lookup.return_value = {"message_id": 555, "chat_id": 1001}

                result = await extract_original_message_info(
                    mock_callback_message, admin_id
                )

                # Verify the result includes Logfire data
                assert result["group_chat_id"] == 1001
                assert result["group_message_id"] == 555
                assert result["user_id"] == 12345
                assert result["username"] == "spammeruser"
                assert result["name"] == "Spammer User"
                assert result["bio"] == "Spammer bio"
                assert result["text"] == "Test spam message"

                # Verify Logfire lookup was called with correct parameters
                mock_lookup.assert_called_once_with(
                    user_id=12345,
                    message_text="Test spam message",
                    forward_date=mock_callback_message.reply_to_message.forward_date,
                    admin_chat_ids=[1001, 1002, 1003],
                )

    @pytest.mark.asyncio
    async def test_logfire_lookup_miss(self, mock_callback_message, mock_bot_get_chat):
        """Test Logfire lookup when no matching message is found."""
        admin_id = 99999

        # Mock admin groups
        with patch(
            "src.app.handlers.private_handlers.get_admin_groups", new_callable=AsyncMock
        ) as mock_get_groups:
            mock_get_groups.return_value = [{"id": 1001}, {"id": 1002}]

            # Mock Logfire lookup returning None
            with patch(
                "src.app.handlers.private_handlers.find_original_message",
                new_callable=AsyncMock,
            ) as mock_lookup:
                mock_lookup.return_value = None

                result = await extract_original_message_info(
                    mock_callback_message, admin_id
                )

                # Verify group IDs are still None (lookup failed)
                assert result["group_chat_id"] is None
                assert result["group_message_id"] is None
                assert result["user_id"] == 12345
                assert result["username"] == "spammeruser"
                assert result["text"] == "Test spam message"

    @pytest.mark.asyncio
    async def test_admin_has_no_groups(self, mock_callback_message, mock_bot_get_chat):
        """Test when admin has no managed groups (lookup skipped)."""
        admin_id = 99999

        # Mock empty admin groups
        with patch(
            "src.app.handlers.private_handlers.get_admin_groups", new_callable=AsyncMock
        ) as mock_get_groups:
            mock_get_groups.return_value = []

            # Logfire lookup should not be called
            with patch(
                "src.app.handlers.private_handlers.find_original_message",
                new_callable=AsyncMock,
            ) as mock_lookup:
                result = await extract_original_message_info(
                    mock_callback_message, admin_id
                )

                # Verify lookup was not called and group IDs are None
                mock_lookup.assert_not_called()
                assert result["group_chat_id"] is None
                assert result["group_message_id"] is None
                assert result["user_id"] == 12345
                assert result["username"] == "spammeruser"

    @pytest.mark.asyncio
    async def test_channel_forward_metadata_available(self, mock_bot_get_chat):
        """Test that Logfire lookup is not called when forward metadata provides group info."""
        admin_id = 99999

        # Create mock with channel forward metadata
        callback_message = MagicMock(spec=types.Message)
        forwarded_message = MagicMock(spec=types.Message)
        forwarded_message.text = "Channel message"
        forwarded_message.forward_date = datetime.now(timezone.utc)

        # Mock channel origin
        origin = MagicMock(spec=types.MessageOriginChannel)
        origin.type = "channel"
        chat = MagicMock(spec=types.Chat)
        chat.id = 2001
        chat.title = "Spam Channel"
        origin.chat = chat
        origin.message_id = 777
        forwarded_message.forward_origin = origin
        forwarded_message.forward_from = None

        callback_message.reply_to_message = forwarded_message

        # Logfire lookup should not be called since we have metadata
        with patch(
            "src.app.handlers.private_handlers.get_admin_groups", new_callable=AsyncMock
        ) as mock_get_groups:
            with patch(
                "src.app.handlers.private_handlers.find_original_message",
                new_callable=AsyncMock,
            ) as mock_lookup:
                result = await extract_original_message_info(callback_message, admin_id)

                # Verify we got the info from forward metadata
                assert result["group_chat_id"] == 2001
                assert result["group_message_id"] == 777
                assert result["name"] == "Spam Channel"

                # Verify Logfire lookup was not called
                mock_lookup.assert_not_called()
                mock_get_groups.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_user_id_in_forward(self):
        """Test handling when forwarded message has no user information."""
        admin_id = 99999

        # Create mock without user information
        callback_message = MagicMock(spec=types.Message)
        forwarded_message = MagicMock(spec=types.Message)
        forwarded_message.text = "Anonymous message"
        forwarded_message.forward_from = None
        forwarded_message.forward_origin = None  # No origin info

        callback_message.reply_to_message = forwarded_message

        # Should raise OriginalMessageExtractionError
        with pytest.raises(Exception):  # OriginalMessageExtractionError
            await extract_original_message_info(callback_message, admin_id)
