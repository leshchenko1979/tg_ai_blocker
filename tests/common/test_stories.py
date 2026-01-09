import pytest
from unittest.mock import AsyncMock, patch
from src.app.common.stories import collect_user_stories, StorySummary

@pytest.fixture
def mock_mtproto_client():
    with patch("src.app.common.stories.get_mtproto_client") as mock:
        client = AsyncMock()
        mock.return_value = client
        yield client

@pytest.mark.asyncio
async def test_collect_user_stories_success(mock_mtproto_client):
    mock_mtproto_client.call_with_fallback = AsyncMock(return_value=(
        {
            "stories": [
                {
                    "id": 123,
                    "date": 1600000000,
                    "caption": "Check out my new project!",
                    "entities": [
                        {"_": "messageEntityTextUrl", "url": "http://spam.com", "offset": 13, "length": 11}
                    ]
                },
                {
                    "id": 124,
                    "date": 1600000100,
                    "caption": "Just a photo",
                    "_": "storyItem"
                }
            ]
        },
        123456  # successful identifier
    ))

    result = await collect_user_stories(123456, username="testuser")

    assert result is not None
    assert "Caption: Check out my new project!" in result
    assert "Link: http://spam.com" in result
    assert "Caption: Just a photo" in result

    # Verify call_with_fallback was called
    mock_mtproto_client.call_with_fallback.assert_called_once()
    args = mock_mtproto_client.call_with_fallback.call_args
    assert args[0][0] == "stories.getPinnedStories"
    assert args[1]["identifiers"] == ["testuser"]
    assert args[1]["identifier_param"] == "peer"

@pytest.mark.asyncio
async def test_collect_user_stories_no_stories(mock_mtproto_client):
    mock_mtproto_client.call_with_fallback = AsyncMock(return_value=({"stories": []}, "testuser"))
    result = await collect_user_stories(123456, username="testuser")
    assert result is None

@pytest.mark.asyncio
async def test_collect_user_stories_deleted(mock_mtproto_client):
    mock_mtproto_client.call_with_fallback = AsyncMock(return_value=(
        {"stories": [{"_": "storyItemDeleted", "id": 123}]},
        "testuser"
    ))
    result = await collect_user_stories(123456, username="testuser")
    assert result is None

@pytest.mark.asyncio
async def test_collect_user_stories_error(mock_mtproto_client):
    from src.app.common.mtproto_client import MtprotoHttpError
    mock_mtproto_client.call_with_fallback = AsyncMock(side_effect=MtprotoHttpError("MTProto error"))
    result = await collect_user_stories(123456, username="testuser")
    assert result is None

def test_story_summary_formatting():
    summary = StorySummary(
        id=1,
        date=123,
        caption="Click here",
        entities=[{"_": "messageEntityTextUrl", "url": "http://example.com"}]
    )
    s = summary.to_string()
    assert "Caption: Click here" in s
    assert "Link: http://example.com" in s

def test_story_summary_media_only():
    summary = StorySummary(id=1, date=123)
    assert summary.to_string() == "Media story"
