"""Tests for format_chat_or_channel_display."""

import pytest

from src.app.common.utils import format_chat_or_channel_display


class TestFormatChatOrChannelDisplay:
    def test_title_and_username(self):
        assert (
            format_chat_or_channel_display("My Group", "groupname")
            == "My Group (@groupname)"
        )

    def test_title_only(self):
        assert format_chat_or_channel_display("My Group", None) == "My Group"

    def test_default_title(self):
        assert format_chat_or_channel_display(None, None) == "Группа"
        assert format_chat_or_channel_display("", None) == "Группа"

    def test_username_only_uses_default_title(self):
        assert (
            format_chat_or_channel_display(None, "chan")
            == "Группа (@chan)"
        )

    def test_html_escaped(self):
        assert "&lt;" in format_chat_or_channel_display("<script>", "x")
        assert "&amp;" in format_chat_or_channel_display("A & B", "x")
