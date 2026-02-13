"""Tests for extract_first_channel_mention."""

from src.app.spam.linked_channel_mention import extract_first_channel_mention


class TestExtractFirstChannelMention:
    def test_mention_at_start(self):
        assert extract_first_channel_mention("@spamchannel") == "spamchannel"

    def test_mention_in_text(self):
        assert (
            extract_first_channel_mention("Check out @my_channel for more")
            == "my_channel"
        )

    def test_t_me_username(self):
        assert (
            extract_first_channel_mention("Link: https://t.me/example_ch")
            == "example_ch"
        )
        assert (
            extract_first_channel_mention("https://t.me/validname12") == "validname12"
        )

    def test_first_mention_wins(self):
        assert extract_first_channel_mention("@first @second_channel") == "first"

    def test_empty_text(self):
        assert extract_first_channel_mention("") is None

    def test_no_mention(self):
        assert extract_first_channel_mention("No channel here") is None

    def test_entity_mention_dict(self):
        text = "Hello @entityuser world"
        entities = [
            {"type": "mention", "offset": 6, "length": 11},
        ]
        assert extract_first_channel_mention(text, entities) == "entityuser"

    def test_entity_text_link(self):
        text = "Link"
        entities = [
            {"type": "text_link", "url": "https://t.me/mychannel"},
        ]
        assert extract_first_channel_mention(text, entities) == "mychannel"

    def test_short_mention_ignored(self):
        assert extract_first_channel_mention("@ab") is None  # < 5 chars
