"""Edited message handler is registered for moderated groups."""

from src.app.handlers import message_handlers
from src.app.handlers.updates_filter import filter_handle_edited_message


def test_edited_message_handler_registered():
    assert hasattr(message_handlers, "handle_moderated_edited_message")
    assert filter_handle_edited_message is not None
