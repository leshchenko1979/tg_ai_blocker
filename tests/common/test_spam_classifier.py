import pytest
from unittest.mock import patch, AsyncMock
from src.app.common.spam_classifier import (
    ExtractionFailedError,
    extract_spam_score,
    format_spam_request,
    get_system_prompt
)


@pytest.mark.parametrize(
    "response,expected",
    [
        ("да 100%", 100),
        ("нет 42%", -42),
        ("<начало ответа> да 100% <конец ответа>", 100),
        ("<начало ответа> нет 1% <конец ответа>", -1),
        ("<abc> да 77% <xyz>", 77),
        ("<ответ> нет 0% <end>", 0),
        ("да 55% <любой тег>", 55),
        ("нет 12% <abc>", -12),
        ("<abc> да 99% <abc>", 99),
        ("<abc> да 88% <zzz>", 88),
        ("<abc> нет 66% <zzz>", -66),
    ],
)
def test_extract_spam_score_valid(response, expected):
    assert extract_spam_score(response) == expected


@pytest.mark.parametrize(
    "response",
    [
        "что-то не то",
        "<abc> maybe 50% <xyz>",
        "<abc> <xyz>",
        "",
    ],
)
def test_extract_spam_score_invalid(response):
    with pytest.raises(ExtractionFailedError):
        extract_spam_score(response)


def test_format_spam_request_basic():
    req = format_spam_request("Hello", "User", "Bio")
    assert "<текст сообщения>\nHello\n</текст сообщения>" in req
    assert "<имя>User</имя>" in req
    assert "<биография>Bio</биография>" in req
    assert "<истории_пользователя>" not in req
    assert "<связанный_канал>" not in req

def test_format_spam_request_with_stories():
    req = format_spam_request(
        "Hello",
        "User",
        "Bio",
        stories_context="Caption: spam story"
    )
    assert "<истории_пользователя>\nCaption: spam story\n</истории_пользователя>" in req

def test_format_spam_request_with_linked_channel():
    req = format_spam_request(
        "Hello",
        linked_channel_fragment="subscribers=100"
    )
    assert "<связанный_канал>subscribers=100</связанный_канал>" in req

@pytest.mark.asyncio
async def test_get_system_prompt_stories_guidance():
    with patch("src.app.common.spam_classifier.get_spam_examples", new_callable=AsyncMock) as mock_examples:
        mock_examples.return_value = []

        prompt = await get_system_prompt(include_stories_guidance=True)

        assert "Раздел <истории_пользователя> содержит информацию" in prompt
        assert "Считай это ВЫСОКИМ индикатором спама" in prompt

@pytest.mark.asyncio
async def test_get_system_prompt_no_guidance():
    with patch("src.app.common.spam_classifier.get_spam_examples", new_callable=AsyncMock) as mock_examples:
        mock_examples.return_value = []

        prompt = await get_system_prompt(include_stories_guidance=False)

        assert "Раздел <истории_пользователя>" not in prompt
