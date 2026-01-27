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
async def test_handler_deduplicates_repeated_messages():
    bot = DummyBot()
    handler = TelegramLogHandler(
        bot=bot,  # type: ignore
        chat_id=123,
        throttling_capacity=5,
        dedupe_window=60.0,
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.set_event_loop(asyncio.get_running_loop())

    logger = logging.getLogger("tests.telegram_logger.dedupe")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    logger.propagate = False

    logger.error("Duplicate")
    await asyncio.sleep(0.5)
    logger.error("Duplicate")
    await asyncio.sleep(0.5)

    logger.removeHandler(handler)

    assert len(bot.calls) == 1
