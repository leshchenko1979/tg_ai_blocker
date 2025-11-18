import pytest

from app.common.utils import get_dotted_path


@pytest.mark.parametrize(
    "json, path, raise_on_missing, expected",
    [
        (
            {"message": {"chat": {"title": "title", "username": "username"}}},
            "message.chat.title",
            True,
            "title",
        ),
        (
            {"message": {"chat": {"title": "title", "username": "username"}}},
            "*.*.title",
            True,
            "title",
        ),
        (
            {"message": {"chat": {"title": "title", "username": "username"}}},
            "non-existent.path",
            True,
            KeyError,
        ),
        (
            {"message": {"chat": {"title": "title", "username": "username"}}},
            "non-existent.path",
            False,
            None,
        ),
        (
            {"message": {"chat": {"title": "title", "username": "username"}}},
            "non-existent.path",
            True,
            KeyError,
        ),
        (
            {"message": {"chat": {"title": "title", "username": "username"}}},
            "*.*.*",
            False,
            None,
        ),
    ],
)
def test_get_dotted_path(json, path, raise_on_missing, expected):
    if expected is KeyError:
        with pytest.raises(KeyError):
            get_dotted_path(json, path, raise_on_missing)
    else:
        assert get_dotted_path(json, path, raise_on_missing) == expected
