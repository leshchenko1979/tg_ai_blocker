import pytest

from src.app.common.spam_classifier import ExtractionFailedError, extract_spam_score


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
