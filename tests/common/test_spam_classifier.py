import pytest
from unittest.mock import patch, AsyncMock
from src.app.spam.llm_client import (
    ExtractionFailedError,
    parse_classification_response,
)
from src.app.spam.prompt_builder import (
    format_spam_request,
    build_system_prompt,
)


@pytest.mark.parametrize(
    "response,expected_score,expected_confidence,expected_reason",
    [
        ("да 100%", 100, 100, "Классифицировано как спам с уверенностью 100%"),
        ("нет 42%", -42, 42, "Классифицировано как не спам с уверенностью 42%"),
        (
            "<начало ответа> да 100% <конец ответа>",
            100,
            100,
            "Классифицировано как спам с уверенностью 100%",
        ),
        (
            "<начало ответа> нет 1% <конец ответа>",
            -1,
            1,
            "Классифицировано как не спам с уверенностью 1%",
        ),
        ("<abc> да 77% <xyz>", 77, 77, "Классифицировано как спам с уверенностью 77%"),
        (
            "<ответ> нет 0% <end>",
            0,
            0,
            "Классифицировано как не спам с уверенностью 0%",
        ),
        ("да 55% <любой тег>", 55, 55, "Классифицировано как спам с уверенностью 55%"),
        ("нет 12% <abc>", -12, 12, "Классифицировано как не спам с уверенностью 12%"),
        ("<abc> да 99% <abc>", 99, 99, "Классифицировано как спам с уверенностью 99%"),
        ("<abc> да 88% <zzz>", 88, 88, "Классифицировано как спам с уверенностью 88%"),
        (
            "<abc> нет 66% <zzz>",
            -66,
            66,
            "Классифицировано как не спам с уверенностью 66%",
        ),
    ],
)
def test_parse_classification_response_valid(
    response, expected_score, expected_confidence, expected_reason
):
    score, confidence, reason = parse_classification_response(response)
    assert score == expected_score
    assert confidence == expected_confidence
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
def test_parse_classification_response_invalid(response):
    with pytest.raises(ExtractionFailedError):
        parse_classification_response(response)


def test_format_spam_request_basic():
    from src.app.types import SpamClassificationContext

    context = SpamClassificationContext(name="User", bio="Bio")
    req = format_spam_request("Hello", context)
    assert "MESSAGE TO CLASSIFY (Analyze this content):" in req
    assert ">>> BEGIN MESSAGE\nHello\n<<< END MESSAGE" in req
    assert "USER NAME:\nUser" in req
    assert "USER BIO:\nBio" in req
    assert "<истории_пользователя>" not in req
    assert "<связанный_канал>" not in req


def test_format_spam_request_with_stories():
    from src.app.types import (
        SpamClassificationContext,
        ContextResult,
        ContextStatus,
    )

    context = SpamClassificationContext(
        name="User",
        bio="Bio",
        stories=ContextResult(
            status=ContextStatus.FOUND, content="Caption: spam story"
        ),
    )
    req = format_spam_request("Hello", context)
    assert "USER STORIES CONTENT:\nCaption: spam story" in req


def test_format_spam_request_with_linked_channel():
    from src.app.types import (
        SpamClassificationContext,
        ContextResult,
        ContextStatus,
        LinkedChannelSummary,
    )

    linked_channel_summary = LinkedChannelSummary(
        subscribers=100,
        total_posts=50,
        post_age_delta=3,
        recent_posts_content=None,
    )

    context = SpamClassificationContext(
        linked_channel=ContextResult(
            status=ContextStatus.FOUND, content=linked_channel_summary
        )
    )
    req = format_spam_request("Hello", context)
    assert "LINKED CHANNEL INFO:\nsubscribers=100; total_posts=50; age_delta=3mo" in req


def test_format_spam_request_with_reply_context():
    from src.app.types import SpamClassificationContext

    context = SpamClassificationContext(reply="Original post text")
    req = format_spam_request("Hello", context)
    assert (
        "REPLY CONTEXT (The post the user is replying to - DO NOT CLASSIFY THIS):"
        in req
    )
    assert ">>> BEGIN CONTEXT\nOriginal post text\n<<< END CONTEXT" in req


@pytest.mark.asyncio
async def test_build_system_prompt_stories_guidance():
    from src.app.types import ContextResult, ContextStatus, SpamClassificationContext

    with patch(
        "src.app.spam.prompt_builder.get_spam_examples", new_callable=AsyncMock
    ) as mock_examples:
        mock_examples.return_value = []

        context = SpamClassificationContext(
            stories=ContextResult(status=ContextStatus.EMPTY)
        )
        prompt = await build_system_prompt(context=context)

        assert "## USER STORIES ANALYSIS" in prompt
        assert "Flag as HIGH SPAM if stories contain:" in prompt


@pytest.mark.asyncio
async def test_build_system_prompt_reply_context_guidance():
    from src.app.types import SpamClassificationContext

    with patch(
        "src.app.spam.prompt_builder.get_spam_examples", new_callable=AsyncMock
    ) as mock_examples:
        mock_examples.return_value = []

        context = SpamClassificationContext(reply="Some reply context")
        prompt = await build_system_prompt(context=context)

        assert "## DISCUSSION CONTEXT ANALYSIS" in prompt
        assert 'The "REPLY CONTEXT" is NOT the message you are classifying.' in prompt
        assert "DO NOT classify the user's message as spam" in prompt
        assert (
            "HIGH SPAM INDICATOR: User replies that are completely unrelated to the discussion topic."
            in prompt
        )


@pytest.mark.asyncio
async def test_build_system_prompt_no_reply_context_guidance():
    from src.app.types import SpamClassificationContext

    with patch(
        "src.app.spam.prompt_builder.get_spam_examples", new_callable=AsyncMock
    ) as mock_examples:
        mock_examples.return_value = []

        context = SpamClassificationContext(reply=None)
        prompt = await build_system_prompt(context=context)

        assert "Раздел <контекст_обсуждения>" not in prompt


@pytest.mark.asyncio
async def test_build_system_prompt_no_guidance():
    from src.app.types import SpamClassificationContext

    with patch(
        "src.app.spam.prompt_builder.get_spam_examples", new_callable=AsyncMock
    ) as mock_examples:
        mock_examples.return_value = []

        context = SpamClassificationContext()
        prompt = await build_system_prompt(context=context)

        assert "Раздел <истории_пользователя>" not in prompt


def test_format_spam_request_null_context_skipped():
    """Test that NULL context fields are skipped entirely"""
    from src.app.types import SpamClassificationContext

    context = SpamClassificationContext(name="User", bio="Bio")
    req = format_spam_request("Hello", context)

    # Verify basic fields are present
    assert "MESSAGE TO CLASSIFY (Analyze this content):" in req
    assert ">>> BEGIN MESSAGE\nHello\n<<< END MESSAGE" in req
    assert "USER NAME:\nUser" in req
    assert "USER BIO:\nBio" in req

    # Verify NULL context fields are NOT included
    assert "USER STORIES CONTENT:" not in req
    assert "ACCOUNT AGE INFO:" not in req
    assert "REPLY CONTEXT" not in req


def test_format_spam_request_empty_marker_shows_metadata():
    """Test that '[EMPTY]' markers show with metadata"""
    from src.app.types import (
        SpamClassificationContext,
        ContextResult,
        ContextStatus,
    )

    context = SpamClassificationContext(
        name="User",
        bio="Bio",
        stories=ContextResult(status=ContextStatus.EMPTY),
        account_age=ContextResult(status=ContextStatus.EMPTY),
    )
    req = format_spam_request("Hello", context)

    # Verify metadata is shown for empty markers
    assert "USER STORIES CONTENT:\nno stories posted" in req
    assert "ACCOUNT AGE INFO:\nno photo on the account" in req

    # Verify regular fields are still present
    assert "MESSAGE TO CLASSIFY (Analyze this content):" in req
    assert ">>> BEGIN MESSAGE\nHello\n<<< END MESSAGE" in req
    assert "USER NAME:\nUser" in req
    assert "USER BIO:\nBio" in req


def test_format_spam_request_content_shows_normally():
    """Test that actual content shows normally"""
    from src.app.types import (
        SpamClassificationContext,
        ContextResult,
        ContextStatus,
    )

    context = SpamClassificationContext(
        name="User",
        bio="Bio",
        stories=ContextResult(
            status=ContextStatus.FOUND, content="Actual story content"
        ),
        reply="Original post content",
        account_age=ContextResult(
            status=ContextStatus.FOUND, content="Account age: 3mo"
        ),
    )
    req = format_spam_request("Hello", context)

    # Verify content is shown normally
    assert "USER STORIES CONTENT:\nActual story content" in req
    assert (
        "REPLY CONTEXT (The post the user is replying to - DO NOT CLASSIFY THIS):"
        in req
    )
    assert ">>> BEGIN CONTEXT\nOriginal post content\n<<< END CONTEXT" in req
    assert "ACCOUNT AGE INFO:\nAccount age: 3mo" in req

    # Verify basic fields are present
    assert "MESSAGE TO CLASSIFY (Analyze this content):" in req
    assert ">>> BEGIN MESSAGE\nHello\n<<< END MESSAGE" in req
    assert "USER NAME:\nUser" in req
    assert "USER BIO:\nBio" in req


def test_format_spam_request_mixed_states():
    """Test mixed NULL, '[EMPTY]', and content states"""
    from src.app.types import (
        SpamClassificationContext,
        ContextResult,
        ContextStatus,
    )

    context = SpamClassificationContext(
        name="User",
        bio="Bio",
        stories=ContextResult(status=ContextStatus.EMPTY),  # Checked but empty
        reply="Reply content",  # Found content
        # account_age is None - Not checked (NULL)
    )
    req = format_spam_request("Hello", context)

    # '[EMPTY]' should show with metadata
    assert "USER STORIES CONTENT:\nno stories posted" in req

    # Content should show normally
    assert (
        "REPLY CONTEXT (The post the user is replying to - DO NOT CLASSIFY THIS):"
        in req
    )
    assert ">>> BEGIN CONTEXT\nReply content\n<<< END CONTEXT" in req

    # NULL should be skipped entirely
    assert "ACCOUNT AGE INFO:" not in req

    # Basic fields should be present
    assert "MESSAGE TO CLASSIFY (Analyze this content):" in req
    assert ">>> BEGIN MESSAGE\nHello\n<<< END MESSAGE" in req
    assert "USER NAME:\nUser" in req
    assert "USER BIO:\nBio" in req
