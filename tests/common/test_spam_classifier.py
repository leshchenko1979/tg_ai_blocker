import pytest
from unittest.mock import patch, AsyncMock
from src.app.common.spam_classifier import (
    ExtractionFailedError,
    extract_spam_score,
    format_spam_request,
    get_system_prompt
)


@pytest.mark.parametrize(
    "response,expected_score,expected_reason",
    [
        ("да 100%", 100, "Классифицировано как спам с уверенностью 100%"),
        ("нет 42%", -42, "Классифицировано как не спам с уверенностью 42%"),
        ("<начало ответа> да 100% <конец ответа>", 100, "Классифицировано как спам с уверенностью 100%"),
        ("<начало ответа> нет 1% <конец ответа>", -1, "Классифицировано как не спам с уверенностью 1%"),
        ("<abc> да 77% <xyz>", 77, "Классифицировано как спам с уверенностью 77%"),
        ("<ответ> нет 0% <end>", 0, "Классифицировано как не спам с уверенностью 0%"),
        ("да 55% <любой тег>", 55, "Классифицировано как спам с уверенностью 55%"),
        ("нет 12% <abc>", -12, "Классифицировано как не спам с уверенностью 12%"),
        ("<abc> да 99% <abc>", 99, "Классифицировано как спам с уверенностью 99%"),
        ("<abc> да 88% <zzz>", 88, "Классифицировано как спам с уверенностью 88%"),
        ("<abc> нет 66% <zzz>", -66, "Классифицировано как не спам с уверенностью 66%"),
    ],
)
def test_extract_spam_score_valid(response, expected_score, expected_reason):
    score, reason = extract_spam_score(response)
    assert score == expected_score
    assert reason == expected_reason


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
    assert "MESSAGE TO CLASSIFY:\nHello" in req
    assert "USER NAME:\nUser" in req
    assert "USER BIO:\nBio" in req
    assert "<истории_пользователя>" not in req
    assert "<связанный_канал>" not in req

def test_format_spam_request_with_stories():
    req = format_spam_request(
        "Hello",
        "User",
        "Bio",
        stories_context="Caption: spam story"
    )
    assert "USER STORIES CONTENT:\nCaption: spam story" in req

def test_format_spam_request_with_linked_channel():
    req = format_spam_request(
        "Hello",
        linked_channel_fragment="subscribers=100"
    )
    assert "LINKED CHANNEL INFO:\nsubscribers=100" in req


def test_format_spam_request_with_reply_context():
    req = format_spam_request(
        "Hello",
        reply_context="Original post text"
    )
    assert "ORIGINAL POST BEING REPLIED TO:\nOriginal post text" in req

@pytest.mark.asyncio
async def test_get_system_prompt_stories_guidance():
    with patch("src.app.common.spam_classifier.get_spam_examples", new_callable=AsyncMock) as mock_examples:
        mock_examples.return_value = []

        prompt = await get_system_prompt(include_stories_guidance=True)

        assert "## USER STORIES ANALYSIS" in prompt
        assert "Flag as HIGH SPAM if stories contain:" in prompt

@pytest.mark.asyncio
async def test_get_system_prompt_reply_context_guidance():
    with patch("src.app.common.spam_classifier.get_spam_examples", new_callable=AsyncMock) as mock_examples:
        mock_examples.return_value = []

        prompt = await get_system_prompt(include_reply_context_guidance=True)

        assert "## DISCUSSION CONTEXT ANALYSIS" in prompt
        assert "IMPORTANT: This context is provided ONLY to evaluate if the user's reply is relevant." in prompt
        assert "DO NOT score this context content as spam" in prompt
        assert "HIGH SPAM INDICATOR: User replies that are completely unrelated to the discussion topic." in prompt

@pytest.mark.asyncio
async def test_get_system_prompt_no_reply_context_guidance():
    with patch("src.app.common.spam_classifier.get_spam_examples", new_callable=AsyncMock) as mock_examples:
        mock_examples.return_value = []

        prompt = await get_system_prompt(include_reply_context_guidance=False)

        assert "Раздел <контекст_обсуждения>" not in prompt

@pytest.mark.asyncio
async def test_get_system_prompt_no_guidance():
    with patch("src.app.common.spam_classifier.get_spam_examples", new_callable=AsyncMock) as mock_examples:
        mock_examples.return_value = []

        prompt = await get_system_prompt(include_stories_guidance=False)

        assert "Раздел <истории_пользователя>" not in prompt
