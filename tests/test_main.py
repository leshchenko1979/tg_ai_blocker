import json

import pytest

from app.common.webhook_errors import RetryableWebhookError
from app.main import handle_retryable_webhook_error


def test_main_imports():
    pass


@pytest.mark.asyncio
async def test_retryable_webhook_error_returns_503():
    class FakeSpan:
        tags = None

    resp = await handle_retryable_webhook_error(
        FakeSpan(),
        RetryableWebhookError("All spam classifiers failed"),
        12.5,
    )
    assert resp.status == 503
    body = json.loads(resp.text)
    assert body["retry"] is True
    assert "classifiers failed" in body["error"]
