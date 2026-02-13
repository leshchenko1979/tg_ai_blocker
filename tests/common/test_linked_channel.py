"""Test linked channel extraction after refactoring to direct MTProto approach."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.app.types import ContextStatus, LinkedChannelSummary, SpamClassificationContext
from src.app.spam.user_profile import (
    _resolve_username_to_channel_id,
    collect_user_context,
    collect_channel_summary_by_id,
)


class TestLinkedChannelExtraction:
    """Test the refactored linked channel extraction that goes directly to MTProto."""

    @pytest.mark.asyncio
    async def test_collect_user_context_uses_mtproto_directly(self):
        """Test that collect_user_context goes directly to MTProto without bot calls."""
        user_id = 12345

        # Mock MTProto client
        mock_client = MagicMock()

        # Mock call for users.getFullUser, channels.getFullChannel, and messages.getHistory
        mock_client.call = AsyncMock(
            side_effect=[
                {"full_user": {"personal_channel_id": 67890}},  # users.getFullUser
                {"full_chat": {"participants_count": 1000}},  # channels.getFullChannel
                {"messages": [], "count": 0},  # messages.getHistory (recent posts)
            ]
        )

        with patch(
            "src.app.spam.user_profile.get_mtproto_client", return_value=mock_client
        ):
            result = await collect_user_context(user_id, username="testuser")

            # Verify call was made for users.getFullUser, channels.getFullChannel, and messages.getHistory
            assert mock_client.call.call_count == 3
            # First call: users.getFullUser
            first_call = mock_client.call.call_args_list[0]
            assert first_call[0][0] == "users.getFullUser"
            assert first_call[1]["params"]["id"] == "testuser"
            # Second call: channels.getFullChannel
            second_call = mock_client.call.call_args_list[1]
            assert second_call[0][0] == "channels.getFullChannel"
            assert second_call[1]["params"]["channel"] == 67890

            # Third call: messages.getHistory (recent posts)
            third_call = mock_client.call.call_args_list[2]
            assert third_call[0][0] == "messages.getHistory"

            # Verify we got the expected result
            assert isinstance(result, SpamClassificationContext)
            assert result.linked_channel is not None
            from src.app.types import ContextStatus

            assert result.linked_channel.status == ContextStatus.FOUND
            assert isinstance(result.linked_channel.content, LinkedChannelSummary)
            assert result.linked_channel.content.subscribers == 1000
            assert (
                result.linked_channel.content.total_posts == 0
            )  # From the mocked messages.getHistory response
            assert (
                result.linked_channel.content.post_age_delta is None
            )  # Channel has no posts

    @pytest.mark.asyncio
    async def test_collect_user_context_no_linked_channel(self):
        """Test handling of users without linked channels."""
        user_id = 12345

        # Mock MTProto client - user has no linked channel
        mock_client = MagicMock()
        mock_client.call = AsyncMock(
            return_value={"full_user": {}}  # No personal_channel_id
        )

        with patch(
            "src.app.spam.user_profile.get_mtproto_client", return_value=mock_client
        ):
            result = await collect_user_context(user_id, username="testuser")

            # Should return SpamClassificationContext with empty linked_channel when no linked channel
            assert isinstance(result, SpamClassificationContext)
            assert result.linked_channel.status == ContextStatus.EMPTY

            # Verify call was made
            mock_client.call.assert_called_once()

    @pytest.mark.asyncio
    async def test_collect_channel_summary_by_id_uses_username(self):
        """Test that collect_channel_summary_by_id uses username if provided."""
        channel_id = -10012345
        username = "testchannel"

        mock_client = MagicMock()
        mock_client.call = AsyncMock(
            side_effect=[
                {
                    "full_chat": {"participants_count": 500},
                    "users": [],
                },  # channels.getFullChannel
                {"messages": [], "count": 0},  # messages.getHistory (recent posts)
                {"messages": [], "count": 0},  # messages.getHistory (edge message)
            ]
        )

        with patch(
            "src.app.spam.user_profile.get_mtproto_client", return_value=mock_client
        ):
            result = await collect_channel_summary_by_id(channel_id, username=username)

            # Verify call was made with username
            assert (
                mock_client.call.call_count >= 1
            )  # At least channels.getFullChannel call
            first_call = mock_client.call.call_args_list[0]
            assert first_call[0][0] == "channels.getFullChannel"
            assert first_call[1]["params"]["channel"] == username

            # Verify result
            assert result.status == ContextStatus.FOUND
            assert result.content.subscribers == 500
            assert result.content.users is not None

    @pytest.mark.asyncio
    async def test_collect_channel_summary_by_id_uses_only_username(self):
        """Test that collect_channel_summary_by_id uses only username when available."""
        channel_id = -10012345
        mtproto_id = 12345
        username = "testchannel"

        mock_client = MagicMock()

        # Mock call to return channel data (uses username since it's available)
        mock_client.call = AsyncMock(
            side_effect=[
                {
                    "full_chat": {"participants_count": 500},
                    "users": [],
                },  # channels.getFullChannel
                {"messages": [], "count": 0},  # messages.getHistory (recent posts)
            ]
        )

        with patch(
            "src.app.spam.user_profile.get_mtproto_client", return_value=mock_client
        ):
            result = await collect_channel_summary_by_id(channel_id, username=username)

            # Verify call was made with username (preferred when available)
            assert mock_client.call.call_count >= 1
            first_call = mock_client.call.call_args_list[0]
            assert first_call[0][0] == "channels.getFullChannel"
            assert first_call[1]["params"]["channel"] == username

            # Verify result
            assert result.status == ContextStatus.FOUND
            assert result.content.subscribers == 500


class TestResolveUsernameToChannelId:
    """Unit tests for _resolve_username_to_channel_id (no integration)."""

    @pytest.mark.asyncio
    async def test_returns_channel_id_for_channel(self):
        mock_chat = MagicMock()
        mock_chat.type = "channel"
        mock_chat.id = -1001234567890

        with patch("src.app.spam.user_profile.bot") as mock_bot:
            mock_bot.get_chat = AsyncMock(return_value=mock_chat)
            result = await _resolve_username_to_channel_id("mychannel")
        assert result == -1001234567890
        mock_bot.get_chat.assert_awaited_once_with("@mychannel")

    @pytest.mark.asyncio
    async def test_returns_channel_id_for_supergroup(self):
        mock_chat = MagicMock()
        mock_chat.type = "supergroup"
        mock_chat.id = -1009876543210

        with patch("src.app.spam.user_profile.bot") as mock_bot:
            mock_bot.get_chat = AsyncMock(return_value=mock_chat)
            result = await _resolve_username_to_channel_id("mygroup")
        assert result == -1009876543210

    @pytest.mark.asyncio
    async def test_returns_none_for_private_chat(self):
        mock_chat = MagicMock()
        mock_chat.type = "private"

        with patch("src.app.spam.user_profile.bot") as mock_bot:
            mock_bot.get_chat = AsyncMock(return_value=mock_chat)
            result = await _resolve_username_to_channel_id("someuser")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_error(self):
        with patch("src.app.spam.user_profile.bot") as mock_bot:
            mock_bot.get_chat = AsyncMock(side_effect=Exception("Chat not found"))
            result = await _resolve_username_to_channel_id("nonexistent")
        assert result is None
