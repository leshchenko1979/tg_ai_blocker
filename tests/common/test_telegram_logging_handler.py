import asyncio
import logging

import pytest

from app.common.telegram_logging_handler import TelegramLogHandler


class DummyBot:
    def __init__(self):
        self.calls = []

    async def send_message(
        self,
        chat_id,
        text,
        parse_mode=None,
        disable_web_page_preview=None,
    ):
        self.calls.append(
            {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": disable_web_page_preview,
            }
        )


@pytest.mark.asyncio
async def test_handler_flushes_after_loop_registration():
    bot = DummyBot()
    handler = TelegramLogHandler(
        bot=bot,  # type: ignore
        chat_id=123,
        throttling_capacity=5,
        dedupe_window=0.5,
    )
    handler.setFormatter(logging.Formatter("%(message)s"))

    logger = logging.getLogger("tests.telegram_logger.flush")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    logger.propagate = False

    logger.warning("First warning")
    assert bot.calls == []

    handler.set_event_loop(asyncio.get_running_loop())

    await asyncio.sleep(0.5)  # Give time for background task to process

    logger.removeHandler(handler)

    assert len(bot.calls) == 1
    payload = bot.calls[0]
    assert payload["chat_id"] == 123
    assert payload["parse_mode"] == "HTML"
    assert "First warning" in payload["text"]


@pytest.mark.asyncio
async def test_handler_drains_queue_on_stop():
    """stop() drains any remaining queued messages, even if the task is still running."""
    bot = DummyBot()
    handler = TelegramLogHandler(
        bot=bot,  # type: ignore
        chat_id=123,
        throttling_capacity=999,  # no throttle limit
        dedupe_window=0.0,
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    loop = asyncio.get_running_loop()
    handler.set_event_loop(loop)

    logger = logging.getLogger("tests.telegram_logger.drain")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    logger.propagate = False

    # Queue a message (will be processed by the background task)
    logger.warning("queued before stop")
    await asyncio.sleep(0.3)

    # While task is still running, call stop() - it should drain
    await handler.stop(timeout=5.0)

    # Exactly 1 call (the one processed before stop) — drain works
    assert len(bot.calls) == 1
    assert "queued before stop" in bot.calls[0]["text"]


@pytest.mark.asyncio
async def test_handler_stop_drains_remaining_on_timeout():
    """If stop() times out waiting for the task, it still drains the queue."""
    bot = DummyBot()
    handler = TelegramLogHandler(
        bot=bot,  # type: ignore
        chat_id=123,
        throttling_capacity=999,
        dedupe_window=0.0,
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.set_event_loop(asyncio.get_running_loop())

    logger = logging.getLogger("tests.telegram_logger.timeout_drain")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    logger.propagate = False

    # Queue 3 messages
    logger.warning("msg1")
    logger.warning("msg2")
    logger.warning("msg3")

    # stop() with a very short timeout — task won't finish in time
    await handler.stop(timeout=0.01)

    # All 3 messages should be drained despite timeout
    assert len(bot.calls) == 3
    assert bot.calls[0]["text"] == "<pre>msg1</pre>"
    assert bot.calls[1]["text"] == "<pre>msg2</pre>"
    assert bot.calls[2]["text"] == "<pre>msg3</pre>"
