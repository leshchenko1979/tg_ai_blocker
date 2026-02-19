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
    async def test_collect_user_context_uses_mtproto_with_username(self):
        """Test that collect_user_context resolves username via Bot API before MTProto (no ID-only queries)."""
        user_id = 12345

        # Mock Bot API: resolve channel ID to username (MTProto ID-Query Prohibition)
        mock_chat = MagicMock()
        mock_chat.id = 67890
        mock_chat.username = "linkedchannel"

        mock_client = MagicMock()
        mock_client.call = AsyncMock(
            side_effect=[
                {"full_user": {"personal_channel_id": 67890}},  # users.getFullUser
                {"full_chat": {"participants_count": 1000}},  # channels.getFullChannel
                {"messages": [], "count": 0},  # messages.getHistory (recent posts)
                {"messages": [], "count": 0},  # messages.getHistory (edge message)
            ]
        )

        get_chat_mock = AsyncMock(return_value=mock_chat)
        with (
            patch(
                "src.app.spam.user_profile.get_mtproto_client", return_value=mock_client
            ),
            patch("src.app.spam.user_profile.bot.get_chat", get_chat_mock),
        ):
            result = await collect_user_context(user_id, username="testuser")

            # bot.get_chat called to resolve channel_id -> username
            get_chat_mock.assert_called_once_with(67890)

            # MTProto: users.getFullUser, channels.getFullChannel (with username), messages.getHistory
            assert mock_client.call.call_count >= 3
            first_call = mock_client.call.call_args_list[0]
            assert first_call[0][0] == "users.getFullUser"
            second_call = mock_client.call.call_args_list[1]
            assert second_call[0][0] == "channels.getFullChannel"
            assert (
                second_call[1]["params"]["channel"] == "linkedchannel"
            )  # username, not ID

            assert isinstance(result, SpamClassificationContext)
            assert result.linked_channel is not None
            assert result.linked_channel.status == ContextStatus.FOUND
            assert isinstance(result.linked_channel.content, LinkedChannelSummary)
            assert result.linked_channel.content.subscribers == 1000

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
    async def test_collect_user_context_skips_mtproto_when_chat_not_found(self):
        """When personal_channel_id exists but bot.get_chat fails, skip MTProto by ID (ID-Query Prohibition)."""
        mock_client = MagicMock()
        mock_client.call = AsyncMock(
            return_value={"full_user": {"personal_channel_id": 67890}}
        )
        get_chat_mock = AsyncMock(side_effect=Exception("Bad Request: chat not found"))

        with (
            patch(
                "src.app.spam.user_profile.get_mtproto_client", return_value=mock_client
            ),
            patch("src.app.spam.user_profile.bot.get_chat", get_chat_mock),
        ):
            result = await collect_user_context(12345, username="testuser")

            get_chat_mock.assert_called_once_with(67890)
            # Only users.getFullUser, no channels.getFullChannel (would query by ID)
            assert mock_client.call.call_count == 1
            assert result.linked_channel.status == ContextStatus.EMPTY

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
