"""Test linked channel extraction after refactoring to direct MTProto approach."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.app.types import ContextStatus
from src.app.types import LinkedChannelSummary, UserContext
from src.app.spam.user_profile import (
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
            assert isinstance(result, UserContext)
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

            # Should return UserContext with empty linked_channel when no linked channel
            assert isinstance(result, UserContext)
            from src.app.types import ContextStatus

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
