"""Test linked channel extraction after refactoring to direct MTProto approach."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.app.spam.context_types import ContextStatus
from src.app.spam.context_types import LinkedChannelSummary, UserContext
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

        # Mock call_with_fallback for both getFullUser and getFullChannel
        mock_client.call_with_fallback = AsyncMock(
            side_effect=[
                (
                    {"full_user": {"personal_channel_id": 67890}},
                    user_id,
                ),  # getFullUser
                ({"full_chat": {"participants_count": 1000}}, 67890),  # getFullChannel
            ]
        )

        # Mock call for messages.getHistory (called once for recent posts content)
        mock_client.call = AsyncMock(return_value={"messages": [], "count": 0})

        with patch(
            "src.app.spam.user_profile.get_mtproto_client", return_value=mock_client
        ):
            result = await collect_user_context(user_id, username="testuser")

            # Verify call_with_fallback was called for both getFullUser and getFullChannel
            assert mock_client.call_with_fallback.call_count == 2
            # First call: getFullUser
            first_call = mock_client.call_with_fallback.call_args_list[0]
            assert first_call[0][0] == "users.getFullUser"
            assert first_call[1]["identifiers"] == ["testuser"]
            assert first_call[1]["identifier_param"] == "id"
            # Second call: getFullChannel
            second_call = mock_client.call_with_fallback.call_args_list[1]
            assert second_call[0][0] == "channels.getFullChannel"
            assert second_call[1]["identifiers"] == [67890]
            assert second_call[1]["identifier_param"] == "channel"

            # Verify regular call was made for messages.getHistory (called once for recent posts)
            assert mock_client.call.call_count == 1

            # Verify we got the expected result
            assert isinstance(result, UserContext)
            assert result.linked_channel is not None
            from src.app.spam.context_types import ContextStatus
            assert result.linked_channel.status == ContextStatus.FOUND
            assert isinstance(result.linked_channel.content, LinkedChannelSummary)
            assert result.linked_channel.content.subscribers == 1000
            assert (
                result.linked_channel.content.total_posts == 0
            )  # From the mocked messages.getHistory response
            assert result.linked_channel.content.post_age_delta is None  # Channel has no posts

    @pytest.mark.asyncio
    async def test_collect_user_context_no_linked_channel(self):
        """Test handling of users without linked channels."""
        user_id = 12345

        # Mock MTProto client - user has no linked channel
        mock_client = MagicMock()
        mock_client.call_with_fallback = AsyncMock(
            return_value=({"full_user": {}}, user_id)  # No personal_channel_id
        )

        with patch(
            "src.app.spam.user_profile.get_mtproto_client", return_value=mock_client
        ):
            result = await collect_user_context(user_id, username="testuser")

            # Should return UserContext with empty linked_channel when no linked channel
            assert isinstance(result, UserContext)
            from src.app.spam.context_types import ContextStatus
            assert result.linked_channel.status == ContextStatus.EMPTY

            # Verify call_with_fallback was called
            mock_client.call_with_fallback.assert_called_once()

    @pytest.mark.asyncio
    async def test_collect_channel_summary_by_id_uses_username(self):
        """Test that collect_channel_summary_by_id uses username if provided."""
        channel_id = -10012345
        username = "testchannel"

        mock_client = MagicMock()
        mock_client.call_with_fallback = AsyncMock(
            return_value=(
                {"full_chat": {"participants_count": 500}},
                username,  # successful identifier
            )
        )
        mock_client.call = AsyncMock(return_value={"messages": [], "count": 0})

        with patch(
            "src.app.spam.user_profile.get_mtproto_client", return_value=mock_client
        ):
            result = await collect_channel_summary_by_id(channel_id, username=username)

            # Verify call_with_fallback was called with username first
            mock_client.call_with_fallback.assert_called_once()
            call_args = mock_client.call_with_fallback.call_args
            assert call_args[0][0] == "channels.getFullChannel"
            assert call_args[1]["identifiers"] == [
                username
            ]  # only username since it's available
            assert call_args[1]["identifier_param"] == "channel"

            # Verify result
            assert result.status == ContextStatus.FOUND
            assert result.content.subscribers == 500

    @pytest.mark.asyncio
    async def test_collect_channel_summary_by_id_uses_only_username(self):
        """Test that collect_channel_summary_by_id uses only username when available."""
        channel_id = -10012345
        mtproto_id = 12345
        username = "testchannel"

        mock_client = MagicMock()

        # Mock call_with_fallback to simulate fallback behavior (username fails, ID succeeds)
        mock_client.call_with_fallback = AsyncMock(
            return_value=(
                {"full_chat": {"participants_count": 500}},
                mtproto_id,  # successful identifier (ID, not username)
            )
        )
        mock_client.call = AsyncMock(return_value={"messages": [], "count": 0})

        with patch(
            "src.app.spam.user_profile.get_mtproto_client", return_value=mock_client
        ):
            result = await collect_channel_summary_by_id(channel_id, username=username)

            # Verify call_with_fallback was called with both identifiers
            mock_client.call_with_fallback.assert_called_once()
            call_args = mock_client.call_with_fallback.call_args
            assert call_args[0][0] == "channels.getFullChannel"
            assert call_args[1]["identifiers"] == [
                username
            ]  # only username since it's available
            assert call_args[1]["identifier_param"] == "channel"

            # Verify result
            assert result.status == ContextStatus.FOUND
            assert result.content.subscribers == 500
