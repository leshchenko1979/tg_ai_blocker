import json

import pytest
import yaml
from unittest.mock import patch, AsyncMock
from src.app.spam.llm_client import (
    ExtractionFailedError,
    parse_classification_response,
)
from src.app.spam.prompt_builder import (
    build_system_prompt,
    format_spam_example_input_yaml_card,
    format_spam_request,
)


@pytest.mark.parametrize(
    "response,expected_is_spam,expected_confidence,expected_reason",
    [
        ("да 100%", True, 100, "Классифицировано как спам с уверенностью 100%"),
        ("нет 42%", False, 42, "Классифицировано как не спам с уверенностью 42%"),
        (
            "<начало ответа> да 100% <конец ответа>",
            True,
            100,
            "Классифицировано как спам с уверенностью 100%",
        ),
        (
            "<начало ответа> нет 1% <конец ответа>",
            False,
            1,
            "Классифицировано как не спам с уверенностью 1%",
        ),
        (
            "<abc> да 77% <xyz>",
            True,
            77,
            "Классифицировано как спам с уверенностью 77%",
        ),
        (
            "<ответ> нет 0% <end>",
            False,
            0,
            "Классифицировано как не спам с уверенностью 0%",
        ),
        (
            "да 55% <любой тег>",
            True,
            55,
            "Классифицировано как спам с уверенностью 55%",
        ),
        ("нет 12% <abc>", False, 12, "Классифицировано как не спам с уверенностью 12%"),
        (
            "<abc> да 99% <abc>",
            True,
            99,
            "Классифицировано как спам с уверенностью 99%",
        ),
        (
            "<abc> да 88% <zzz>",
            True,
            88,
            "Классифицировано как спам с уверенностью 88%",
        ),
        (
            "<abc> нет 66% <zzz>",
            False,
            66,
            "Классифицировано как не спам с уверенностью 66%",
        ),
    ],
)
def test_parse_classification_response_valid(
    response, expected_is_spam, expected_confidence, expected_reason
):
    is_spam, confidence, reason = parse_classification_response(response)
    assert is_spam == expected_is_spam
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


def test_parse_classification_response_json_with_trailing_provider_ad():
    """Free-tier models sometimes append ads after valid JSON."""
    response = (
        '{\n    "is_spam": true,\n    "confidence": 100,\n    '
        '"reason": "spam reason"\n}\n\n'
        "Need proxies cheaper than the market?\nhttps://op.wtf"
    )
    is_spam, confidence, reason = parse_classification_response(response)
    assert is_spam is True
    assert confidence == 100
    assert reason == "spam reason"


@pytest.mark.parametrize(
    "response,expected_is_spam,expected_confidence,expected_reason",
    [
        pytest.param(
            '{"is_spam": false, "confidence": 90, "reason": "legit"}',
            False,
            90,
            "legit",
            id="clean-json",
        ),
        pytest.param(
            '  \n{"is_spam": true, "confidence": 50, "reason": "leading space"}',
            True,
            50,
            "leading space",
            id="leading-whitespace",
        ),
        pytest.param(
            'Here is the result:\n{"is_spam": false, "confidence": 80, "reason": "preamble"}',
            False,
            80,
            "preamble",
            id="preamble-before-object",
        ),
        pytest.param(
            "```json\n"
            '{"is_spam": true, "confidence": 10, "reason": "fenced"}\n'
            "```\n"
            "sponsored footer",
            True,
            10,
            "fenced",
            id="markdown-fence-and-footer",
        ),
        pytest.param(
            '{"is_spam": false, "confidence": 0, "reason": "x"} same-line junk',
            False,
            0,
            "x",
            id="same-line-trailing-junk",
        ),
        pytest.param(
            '{"is_spam": true, "confidence": 100, "reason": "brace {in} reason"}',
            True,
            100,
            "brace {in} reason",
            id="reason-with-brace-literals",
        ),
    ],
)
def test_parse_classification_response_json_edge_cases(
    response, expected_is_spam, expected_confidence, expected_reason
):
    is_spam, confidence, reason = parse_classification_response(response)
    assert is_spam == expected_is_spam
    assert confidence == expected_confidence
    assert reason == expected_reason


@pytest.mark.parametrize(
    "response",
    [
        pytest.param("not json {broken", id="truncated-json"),
        pytest.param("[1, 2, 3]", id="json-array-not-object"),
        pytest.param("42", id="json-scalar-no-brace"),
    ],
)
def test_parse_classification_response_json_unparseable(response):
    """Non-object JSON or truncated text must fall through and raise."""
    with pytest.raises(ExtractionFailedError):
        parse_classification_response(response)


def test_parse_classification_response_json_partial_uses_defaults():
    """Omitted optional-style fields fall back to parser defaults."""
    is_spam, confidence, reason = parse_classification_response(
        '{"is_spam": true, "confidence": 77}'
    )
    assert is_spam is True
    assert confidence == 77
    assert reason == "No reason provided"


def test_format_spam_request_basic():
    from src.app.types import SpamClassificationContext

    context = SpamClassificationContext(name="User", bio="Bio")
    req = format_spam_request("Hello", context)
    assert "MESSAGE TO CLASSIFY (Analyze this content):" in req
    assert ">>> BEGIN MESSAGE\nHello\n<<< END MESSAGE" in req
    assert "USER NAME:\nUser" in req
    assert "USER BIO:\nBio" in req
    assert "<<< END MESSAGE\n\n---\n\nUSER NAME:" in req
    assert "<истории_пользователя>" not in req
    assert "<связанный_канал>" not in req


def test_format_spam_request_empty_context_no_delimiter():
    """No sender context: no --- delimiter after message block."""
    from src.app.types import SpamClassificationContext

    req = format_spam_request("Only this", SpamClassificationContext())
    assert ">>> BEGIN MESSAGE\nOnly this\n<<< END MESSAGE" in req
    assert "\n---\n" not in req


def test_format_spam_request_deterministic_section_order():
    """Context sections appear in fixed order after the delimiter."""
    from datetime import datetime, timedelta, timezone

    from src.app.types import (
        SpamClassificationContext,
        ContextResult,
        ContextStatus,
        LinkedChannelSummary,
        UserAccountInfo,
    )

    linked = LinkedChannelSummary(
        subscribers=1, total_posts=1, post_age_delta=0, recent_posts_content=None
    )
    photo_date = datetime.now(timezone.utc) - timedelta(days=150)
    profile = UserAccountInfo(user_id=1, profile_photo_date=photo_date)
    context = SpamClassificationContext(
        name="N",
        bio="B",
        linked_channel=ContextResult(status=ContextStatus.FOUND, content=linked),
        stories=ContextResult(status=ContextStatus.FOUND, content="story"),
        profile_photo_age=ContextResult(status=ContextStatus.FOUND, content=profile),
        reply="post body",
    )
    req = format_spam_request("msg", context)
    p_bio = req.find("USER BIO:\nB")
    p_linked = req.find("LINKED CHANNEL INFO:")
    p_stories = req.find("USER STORIES CONTENT:")
    p_acc = req.find("ACCOUNT SIGNALS:")
    p_reply = req.find(
        "REPLY CONTEXT (The post the user is replying to - DO NOT CLASSIFY THIS):"
    )
    assert 0 < p_bio < p_linked < p_stories < p_acc < p_reply


def test_format_spam_request_empty_reply_unified_header():
    from src.app.types import SpamClassificationContext

    context = SpamClassificationContext(reply="[EMPTY]")
    req = format_spam_request("Hi", context)
    assert (
        "REPLY CONTEXT (The post the user is replying to - DO NOT CLASSIFY THIS):"
        in req
    )
    assert "[checked, none found]" in req


@pytest.mark.asyncio
async def test_build_system_prompt_requires_reason_in_actual_response():
    with patch(
        "src.app.spam.prompt_builder.get_spam_examples", new_callable=AsyncMock
    ) as mock_examples:
        mock_examples.return_value = []
        prompt = await build_system_prompt()
        assert "EXAMPLE_INPUT_YAML" in prompt
        assert "all three keys, including `reason`" in prompt
        assert "## RESPONSE FORMAT" in prompt
        assert '"is_spam"' in prompt
        assert '"reason"' in prompt
        assert "Confidence calibration policy" in prompt
        assert "use medium confidence for ambiguous cases" in prompt


@pytest.mark.asyncio
async def test_build_system_prompt_reply_context_has_high_confidence_gating():
    from src.app.types import SpamClassificationContext

    with patch(
        "src.app.spam.prompt_builder.get_spam_examples", new_callable=AsyncMock
    ) as mock_examples:
        mock_examples.return_value = []
        prompt = await build_system_prompt(
            context=SpamClassificationContext(reply="context post")
        )
        assert "High-confidence spam (e.g., 90+) requires clear evidence" in prompt
        assert (
            "Do not assign high confidence from weak absence signals alone." in prompt
        )


@pytest.mark.asyncio
async def test_build_system_prompt_few_shot_labels_json_keys():
    """EXAMPLE_LABEL_JSON lines contain only is_spam and confidence."""
    example_row = {
        "text": "spam text",
        "score": 100,
        "name": None,
        "bio": None,
        "linked_channel_fragment": None,
        "stories_context": None,
        "reply_context": None,
        "account_signals_context": None,
    }
    ham_row = {
        "text": "legit",
        "score": 0,
        "name": "U",
        "bio": None,
        "linked_channel_fragment": None,
        "stories_context": None,
        "reply_context": None,
        "account_signals_context": None,
    }
    with patch(
        "src.app.spam.prompt_builder.get_spam_examples", new_callable=AsyncMock
    ) as mock_examples:
        mock_examples.return_value = [example_row, ham_row]
        prompt = await build_system_prompt()
    assert "--- EXAMPLE_INPUT_YAML ---" in prompt
    assert "EXAMPLE_LABEL_JSON:" in prompt
    chunks = prompt.split("--- EXAMPLE_INPUT_YAML ---")[1:]
    assert len(chunks) >= 2
    for chunk in chunks:
        yaml_blob, sep, tail = chunk.partition("\n\nEXAMPLE_LABEL_JSON:\n")
        assert sep
        card = yaml.safe_load(yaml_blob.strip())
        assert set(card.keys()) == {
            "message",
            "user_name",
            "user_bio",
            "linked_channel",
            "stories",
            "reply_context",
            "account_signals",
        }
        label_line = tail.strip().split("\n", 1)[0]
        data = json.loads(label_line)
        assert set(data.keys()) == {"is_spam", "confidence"}
        assert isinstance(data["is_spam"], bool)
        assert isinstance(data["confidence"], int)


def test_format_spam_example_input_yaml_card_roundtrip():
    row = {
        "text": "hello\nworld",
        "name": " N ",
        "bio": None,
        "linked_channel_fragment": "subscribers=1",
        "stories_context": "[EMPTY]",
        "reply_context": "thread",
        "account_signals_context": " photo_age=0mo ",
    }
    dumped = format_spam_example_input_yaml_card(row)
    card = yaml.safe_load(dumped)
    assert card["message"] == "hello\nworld"
    assert card["user_name"] == "N"
    assert card["user_bio"] is None
    assert card["linked_channel"] == "subscribers=1"
    assert card["stories"] == "[EMPTY]"
    assert card["reply_context"] == "thread"
    assert card["account_signals"] == "photo_age=0mo"


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
async def test_build_system_prompt_account_signals_guidance():
    from src.app.types import ContextResult, ContextStatus, SpamClassificationContext

    with patch(
        "src.app.spam.prompt_builder.get_spam_examples", new_callable=AsyncMock
    ) as mock_examples:
        mock_examples.return_value = []

        context = SpamClassificationContext(
            profile_photo_age=ContextResult(status=ContextStatus.EMPTY)
        )
        prompt = await build_system_prompt(context=context)

        assert "## ACCOUNT SIGNALS ANALYSIS" in prompt
        assert "is_premium=true" in prompt or "Telegram Premium" in prompt


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
        assert '"Relevant to discussion" alone does NOT mean legitimate' in prompt
        assert (
            "HIGH SPAM INDICATOR: User replies that are completely unrelated to the discussion topic."
            in prompt
        )


@pytest.mark.asyncio
async def test_build_system_prompt_trojan_horse_guidance():
    """Trojan Horse and signal hierarchy are always present in the prompt."""
    from src.app.types import SpamClassificationContext

    with patch(
        "src.app.spam.prompt_builder.get_spam_examples", new_callable=AsyncMock
    ) as mock_examples:
        mock_examples.return_value = []

        context = SpamClassificationContext(
            reply="Promo post",
            name="Лида | Комменты без усилий",
            bio="ИИ агенты приводят лиды t.me/LeadHunter_robot",
        )
        prompt = await build_system_prompt(context=context)

        assert "## TROJAN HORSE PATTERN (Critical)" in prompt
        assert "Clean message + dirty profile can be SPAM" in prompt
        assert "SIGNAL HIERARCHY" in prompt


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
    assert "ACCOUNT SIGNALS:" not in req
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
        profile_photo_age=ContextResult(status=ContextStatus.EMPTY),
    )
    req = format_spam_request("Hello", context)

    # Verify metadata is shown for empty markers (metric-style phrasing)
    assert "USER STORIES CONTENT:\nno stories posted" in req
    assert "ACCOUNT SIGNALS:\nphoto_age=unknown" in req

    # Verify regular fields are still present
    assert "MESSAGE TO CLASSIFY (Analyze this content):" in req
    assert ">>> BEGIN MESSAGE\nHello\n<<< END MESSAGE" in req
    assert "USER NAME:\nUser" in req
    assert "USER BIO:\nBio" in req


def test_format_spam_request_content_shows_normally():
    """Test that actual content shows normally"""
    from datetime import datetime, timezone

    from src.app.types import (
        SpamClassificationContext,
        ContextResult,
        ContextStatus,
        UserAccountInfo,
    )

    profile = UserAccountInfo(
        user_id=1, profile_photo_date=datetime(2024, 6, 1, tzinfo=timezone.utc)
    )
    context = SpamClassificationContext(
        name="User",
        bio="Bio",
        stories=ContextResult(
            status=ContextStatus.FOUND, content="Actual story content"
        ),
        reply="Original post content",
        profile_photo_age=ContextResult(status=ContextStatus.FOUND, content=profile),
    )
    req = format_spam_request("Hello", context)

    _extracted_from_test_format_spam_request_content_shows_normally_27(
        "USER STORIES CONTENT:\nActual story content",
        req,
        "REPLY CONTEXT (The post the user is replying to - DO NOT CLASSIFY THIS):",
        ">>> BEGIN CONTEXT\nOriginal post content\n<<< END CONTEXT",
    )
    assert f"ACCOUNT SIGNALS:\n{profile.to_prompt_fragment()}" in req

    _extracted_from_test_format_spam_request_content_shows_normally_27(
        "MESSAGE TO CLASSIFY (Analyze this content):",
        req,
        ">>> BEGIN MESSAGE\nHello\n<<< END MESSAGE",
        "USER NAME:\nUser",
    )
    assert "USER BIO:\nBio" in req


# TODO Rename this here and in `test_format_spam_request_content_shows_normally`
def _extracted_from_test_format_spam_request_content_shows_normally_27(
    arg0, req, arg2, arg3
):
    # Verify content is shown normally
    assert arg0 in req
    assert arg2 in req
    assert arg3 in req


def test_format_spam_request_is_premium_bundled():
    from src.app.types import (
        SpamClassificationContext,
        ContextResult,
        ContextStatus,
    )

    context = SpamClassificationContext(
        profile_photo_age=ContextResult(status=ContextStatus.EMPTY),
        is_premium=True,
    )
    req = format_spam_request("Hello", context)
    assert "ACCOUNT SIGNALS:\nphoto_age=unknown\nis_premium=true" in req


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
        # profile_photo_age is None - Not checked (NULL)
    )
    req = format_spam_request("Hello", context)

    _extracted_from_test_format_spam_request_mixed_states_19(
        "USER STORIES CONTENT:\nno stories posted",
        req,
        "REPLY CONTEXT (The post the user is replying to - DO NOT CLASSIFY THIS):",
        ">>> BEGIN CONTEXT\nReply content\n<<< END CONTEXT",
    )
    # NULL should be skipped entirely
    assert "ACCOUNT SIGNALS:" not in req

    _extracted_from_test_format_spam_request_mixed_states_19(
        "MESSAGE TO CLASSIFY (Analyze this content):",
        req,
        ">>> BEGIN MESSAGE\nHello\n<<< END MESSAGE",
        "USER NAME:\nUser",
    )
    assert "USER BIO:\nBio" in req


# TODO Rename this here and in `test_format_spam_request_mixed_states`
def _extracted_from_test_format_spam_request_mixed_states_19(arg0, req, arg2, arg3):
    # '[EMPTY]' should show with metadata
    assert arg0 in req

    # Content should show normally
    assert arg2 in req
    assert arg3 in req
