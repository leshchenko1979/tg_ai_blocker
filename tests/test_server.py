import pytest

from src.app.server import extract_update_type_ignored


class TestExtractUpdateTypeIgnored:
    """Test the extract_update_type_ignored function."""

    def test_edited_message_update(self):
        """Test extraction of edited_message update type."""
        json_update = {
            "update_id": 123456,
            "edited_message": {"message_id": 123, "chat": {"id": -100123}}
        }

        result = extract_update_type_ignored(json_update)
        assert result == "edited_message_ignored"

    def test_message_update(self):
        """Test extraction of message update type."""
        json_update = {
            "update_id": 123456,
            "message": {"message_id": 123, "chat": {"id": -100123}}
        }

        result = extract_update_type_ignored(json_update)
        assert result == "message_ignored"

    def test_callback_query_update(self):
        """Test extraction of callback_query update type."""
        json_update = {
            "update_id": 123456,
            "callback_query": {"id": "123", "data": "test"}
        }

        result = extract_update_type_ignored(json_update)
        assert result == "callback_query_ignored"

    def test_inline_query_update(self):
        """Test extraction of inline_query update type."""
        json_update = {
            "update_id": 123456,
            "inline_query": {"id": "123", "query": "test"}
        }

        result = extract_update_type_ignored(json_update)
        assert result == "inline_query_ignored"

    def test_empty_update(self):
        """Test handling of update with only update_id."""
        json_update = {
            "update_id": 123456
        }

        result = extract_update_type_ignored(json_update)
        assert result == "empty_update_ignored"

    def test_multiple_update_types(self):
        """Test handling of update with multiple update types (edge case)."""
        json_update = {
            "update_id": 123456,
            "message": {"message_id": 123},
            "callback_query": {"id": "123"}
        }

        result = extract_update_type_ignored(json_update)
        assert result == "multiple_types_ignored"