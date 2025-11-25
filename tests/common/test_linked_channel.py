"""Test linked channel extraction after refactoring to direct MTProto approach."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.app.common.linked_channel import (
    collect_linked_channel_summary,
    collect_channel_summary_by_id,
    LinkedChannelSummary,
)


class TestLinkedChannelExtraction:
    """Test the refactored linked channel extraction that goes directly to MTProto."""

    @pytest.mark.asyncio
    async def test_collect_linked_channel_summary_uses_mtproto_directly(self):
        """Test that collect_linked_channel_summary goes directly to MTProto without bot calls."""
        user_id = 12345

        # Mock MTProto client
        mock_client = MagicMock()

        # Mock call_with_fallback for both getFullUser and getFullChannel
        mock_client.call_with_fallback = AsyncMock(side_effect=[
            ({"full_user": {"personal_channel_id": 67890}}, user_id),  # getFullUser
            ({"full_chat": {"participants_count": 1000}}, 67890),     # getFullChannel
        ])

        # Mock call for messages.getHistory (only remaining call)
        mock_client.call = AsyncMock(return_value={"messages": [], "count": 0})

        with patch(
            "src.app.common.linked_channel.get_mtproto_client", return_value=mock_client
        ):
            result = await collect_linked_channel_summary(user_id)

            # Verify call_with_fallback was called for both getFullUser and getFullChannel
            assert mock_client.call_with_fallback.call_count == 2
            # First call: getFullUser
            first_call = mock_client.call_with_fallback.call_args_list[0]
            assert first_call[0][0] == "users.getFullUser"
            assert first_call[1]["identifiers"] == [user_id]
            assert first_call[1]["identifier_param"] == "id"
            # Second call: getFullChannel
            second_call = mock_client.call_with_fallback.call_args_list[1]
            assert second_call[0][0] == "channels.getFullChannel"
            assert second_call[1]["identifiers"] == [67890]
            assert second_call[1]["identifier_param"] == "channel"

            # Verify regular call was made for messages.getHistory
            assert mock_client.call.call_count == 1

            # Verify we got the expected result
            assert isinstance(result, LinkedChannelSummary)
            assert result.subscribers == 1000
            assert (
                result.total_posts == 0
            )  # From the mocked messages.getHistory response
            assert result.post_age_delta is None  # Channel has no posts

    @pytest.mark.asyncio
    async def test_collect_linked_channel_summary_no_linked_channel(self):
        """Test handling of users without linked channels."""
        user_id = 12345

        # Mock MTProto client - user has no linked channel
        mock_client = MagicMock()
        mock_client.call_with_fallback = AsyncMock(return_value=(
            {"full_user": {}},  # No personal_channel_id
            user_id
        ))

        with patch(
            "src.app.common.linked_channel.get_mtproto_client", return_value=mock_client
        ):
            result = await collect_linked_channel_summary(user_id)

            # Should return None when no linked channel
            assert result is None

            # Verify call_with_fallback was called
            mock_client.call_with_fallback.assert_called_once()

    @pytest.mark.asyncio
    async def test_collect_channel_summary_by_id_uses_username(self):
        """Test that collect_channel_summary_by_id uses username if provided."""
        channel_id = -10012345
        username = "testchannel"

        mock_client = MagicMock()
        mock_client.call_with_fallback = AsyncMock(return_value=(
            {"full_chat": {"participants_count": 500}},
            username  # successful identifier
        ))
        mock_client.call = AsyncMock(return_value={"messages": [], "count": 0})

        with patch(
            "src.app.common.linked_channel.get_mtproto_client", return_value=mock_client
        ):
            result = await collect_channel_summary_by_id(channel_id, username=username)

            # Verify call_with_fallback was called with username first
            mock_client.call_with_fallback.assert_called_once()
            call_args = mock_client.call_with_fallback.call_args
            assert call_args[0][0] == "channels.getFullChannel"
            assert call_args[1]["identifiers"] == [username, 12345]  # username first, then mtproto_id
            assert call_args[1]["identifier_param"] == "channel"

            # Verify result
            assert result.subscribers == 500

    @pytest.mark.asyncio
    async def test_collect_channel_summary_by_id_fallback_to_id(self):
        """Test that collect_channel_summary_by_id falls back to ID if username fails."""
        channel_id = -10012345
        mtproto_id = 12345
        username = "testchannel"

        mock_client = MagicMock()

        # Mock call_with_fallback to simulate fallback behavior (username fails, ID succeeds)
        mock_client.call_with_fallback = AsyncMock(return_value=(
            {"full_chat": {"participants_count": 500}},
            mtproto_id  # successful identifier (ID, not username)
        ))
        mock_client.call = AsyncMock(return_value={"messages": [], "count": 0})

        with patch(
            "src.app.common.linked_channel.get_mtproto_client", return_value=mock_client
        ):
            result = await collect_channel_summary_by_id(channel_id, username=username)

            # Verify call_with_fallback was called with both identifiers
            mock_client.call_with_fallback.assert_called_once()
            call_args = mock_client.call_with_fallback.call_args
            assert call_args[0][0] == "channels.getFullChannel"
            assert call_args[1]["identifiers"] == [username, mtproto_id]  # username first, then ID
            assert call_args[1]["identifier_param"] == "channel"

            # Verify result
            assert result.subscribers == 500
