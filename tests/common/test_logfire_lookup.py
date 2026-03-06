"""Unit tests for logfire_lookup module."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from src.app.common.logfire_lookup import find_spam_classification_context
from src.app.types import ContextResult, UserAccountInfo


class TestUserAccountInfoFragmentFromLogfireDict:
    """Tests for UserAccountInfo.fragment_from_logfire_dict."""

    def test_empty_content_returns_unknown(self):
        assert UserAccountInfo.fragment_from_logfire_dict(None) == "photo_age=unknown"
        assert UserAccountInfo.fragment_from_logfire_dict({}) == "photo_age=unknown"
        assert (
            UserAccountInfo.fragment_from_logfire_dict("not a dict")
            == "photo_age=unknown"
        )

    def test_no_profile_photo_date_returns_unknown(self):
        assert (
            UserAccountInfo.fragment_from_logfire_dict({"user_id": 123})
            == "photo_age=unknown"
        )

    def test_valid_iso_date_returns_months(self):
        past = datetime.now(timezone.utc) - timedelta(days=60)
        iso = past.isoformat()
        result = UserAccountInfo.fragment_from_logfire_dict(
            {"user_id": 123, "profile_photo_date": iso}
        )
        assert result.startswith("photo_age=")
        assert "mo" in result
        assert "unknown" not in result

    def test_date_with_z_suffix(self):
        result = UserAccountInfo.fragment_from_logfire_dict(
            {"profile_photo_date": "2026-02-28T10:33:01Z"}
        )
        assert "photo_age=" in result
        assert "mo" in result


class TestContextResultFragmentFromLogfireDict:
    """Tests for ContextResult.fragment_from_logfire_dict."""

    def test_none_or_invalid_returns_none(self):
        assert ContextResult.fragment_from_logfire_dict(None) is None
        assert ContextResult.fragment_from_logfire_dict("str") is None
        assert ContextResult.fragment_from_logfire_dict([]) is None

    def test_status_found_with_string_content(self):
        obj = {"status": "found", "content": "Stories text here", "error": None}
        assert ContextResult.fragment_from_logfire_dict(obj) == "Stories text here"

    def test_status_empty_returns_marker(self):
        obj = {"status": "empty", "content": None, "error": None}
        assert ContextResult.fragment_from_logfire_dict(obj) == "[EMPTY]"

    def test_status_empty_custom_marker(self):
        obj = {"status": "empty", "content": None}
        assert ContextResult.fragment_from_logfire_dict(obj, empty_marker="X") == "X"

    def test_status_failed_or_skipped_returns_none(self):
        assert ContextResult.fragment_from_logfire_dict({"status": "failed"}) is None
        assert ContextResult.fragment_from_logfire_dict({"status": "skipped"}) is None


class TestFindSpamClassificationContext:
    """Tests for find_spam_classification_context two-step lookup."""

    @pytest.mark.asyncio
    async def test_step1_miss_returns_none(self):
        mock_client = MagicMock()
        mock_client.query_json_rows.side_effect = [{"rows": []}]

        with patch(
            "src.app.common.logfire_lookup._get_client", return_value=mock_client
        ):
            result = await find_spam_classification_context(
                message_id=123,
                chat_id=-1001,
                user_id=999,
                forward_date=datetime.now(timezone.utc),
            )

        assert result is None
        assert mock_client.query_json_rows.call_count == 1

    @pytest.mark.asyncio
    async def test_step1_no_trace_id_returns_none(self):
        mock_client = MagicMock()
        mock_client.query_json_rows.side_effect = [{"rows": [{}]}]

        with patch(
            "src.app.common.logfire_lookup._get_client", return_value=mock_client
        ):
            result = await find_spam_classification_context(
                message_id=123,
                chat_id=-1001,
                user_id=999,
                forward_date=datetime.now(timezone.utc),
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_step2_miss_returns_none(self):
        mock_client = MagicMock()
        mock_client.query_json_rows.side_effect = [
            {"rows": [{"trace_id": "trace-abc"}]},
            {"rows": []},
        ]

        with patch(
            "src.app.common.logfire_lookup._get_client", return_value=mock_client
        ):
            result = await find_spam_classification_context(
                message_id=123,
                chat_id=-1001,
                user_id=999,
                forward_date=datetime.now(timezone.utc),
            )

        assert result is None
        assert mock_client.query_json_rows.call_count == 2

    @pytest.mark.asyncio
    async def test_full_success_extracts_all_context(self):
        mock_client = MagicMock()
        mock_client.query_json_rows.side_effect = [
            {"rows": [{"trace_id": "trace-abc"}]},
            {
                "rows": [
                    {
                        "attributes": {
                            "context": {
                                "reply": "Original post the user replied to",
                                "stories": {
                                    "status": "found",
                                    "content": "Story content here",
                                    "error": None,
                                },
                                "account_age": {
                                    "status": "found",
                                    "content": {
                                        "user_id": 123,
                                        "profile_photo_date": "2026-01-15T10:00:00+00:00",
                                    },
                                    "error": None,
                                },
                            }
                        }
                    }
                ]
            },
        ]

        with patch(
            "src.app.common.logfire_lookup._get_client", return_value=mock_client
        ):
            result = await find_spam_classification_context(
                message_id=123,
                chat_id=-1001,
                user_id=999,
                forward_date=datetime.now(timezone.utc),
            )

        assert result is not None
        assert result["reply_context"] == "Original post the user replied to"
        assert result["stories_context"] == "Story content here"
        assert result["account_age_context"] is not None
        assert "photo_age=" in result["account_age_context"]
        assert "mo" in result["account_age_context"]

    @pytest.mark.asyncio
    async def test_empty_stories_and_account_age_markers(self):
        mock_client = MagicMock()
        mock_client.query_json_rows.side_effect = [
            {"rows": [{"trace_id": "trace-xyz"}]},
            {
                "rows": [
                    {
                        "attributes": {
                            "context": {
                                "reply": "Reply text",
                                "stories": {
                                    "status": "empty",
                                    "content": None,
                                    "error": None,
                                },
                                "account_age": {
                                    "status": "empty",
                                    "content": None,
                                    "error": None,
                                },
                            }
                        }
                    }
                ]
            },
        ]

        with patch(
            "src.app.common.logfire_lookup._get_client", return_value=mock_client
        ):
            result = await find_spam_classification_context(
                message_id=456,
                chat_id=-1002,
                user_id=None,
                forward_date=datetime.now(timezone.utc),
            )

        assert result is not None
        assert result["reply_context"] == "Reply text"
        assert result["stories_context"] == "[EMPTY]"
        assert result["account_age_context"] == "[EMPTY]"
