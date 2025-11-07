import asyncio
import html
import logging
import threading
import time
from collections import deque
from concurrent.futures import Future
from typing import Deque, Optional, Tuple

from aiogram import Bot


class TelegramLogHandler(logging.Handler):
    """
    Logging handler that forwards warnings and errors to a Telegram chat.

    The handler buffers log records until the asyncio event loop is available.
    Once a loop is registered (see `set_event_loop`), records are delivered by
    scheduling `bot.send_message` calls on that loop. Delivery is throttled to
    avoid spamming Telegram during error storms.
    """

    MAX_MESSAGE_BODY = 3600  # leave headroom for headers & markup
    MAX_TELEGRAM_LENGTH = 4096

    def __init__(
        self,
        bot: Bot,
        chat_id: int,
        *,
        throttling_window: float = 60.0,
        throttling_capacity: int = 10,
        dedupe_window: float = 15.0,
    ) -> None:
        super().__init__(level=logging.WARNING)
        self._bot = bot
        self._chat_id = chat_id
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock = threading.Lock()
        self._pending: Deque[Tuple[str, logging.LogRecord]] = deque(maxlen=50)
        self._sent_timestamps: Deque[float] = deque(maxlen=throttling_capacity)
        self._throttling_window = throttling_window
        self._dedupe_window = dedupe_window
        self._last_text: Optional[str] = None
        self._last_sent_at: float = 0.0

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """
        Register an asyncio loop used to deliver Telegram messages.
        Flushes any buffered records once the loop becomes available.
        """
        with self._lock:
            self._loop = loop
            pending = list(self._pending)
            self._pending.clear()

        for text, record in pending:
            self._enqueue(text, record)

    def emit(self, record: logging.LogRecord) -> None:
        # Skip logs emitted by this handler to prevent recursion
        if record.name.startswith(__name__):
            return

        try:
            text = self._render_message(record)
        except Exception:
            self.handleError(record)
            return

        with self._lock:
            if self._loop is None:
                self._pending.append((text, record))
                return

        self._enqueue(text, record)

    def _enqueue(self, text: str, record: logging.LogRecord) -> None:
        loop: Optional[asyncio.AbstractEventLoop]
        with self._lock:
            loop = self._loop
            if loop is None:
                self._pending.append((text, record))
                return

            if self._should_dedupe(text):
                return

            if not self._allow_throughput():
                return

            now = time.monotonic()
            self._last_text = text
            self._last_sent_at = now
            self._sent_timestamps.append(now)

        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is loop:
            task = loop.create_task(self._send(text))
            task.add_done_callback(lambda t: self._on_task_done(t, record))
        else:
            future: Future = asyncio.run_coroutine_threadsafe(
                self._send(text),
                loop,
            )
            future.add_done_callback(lambda f: self._on_future_done(f, record))

    def _render_message(self, record: logging.LogRecord) -> str:
        rendered = self.format(record)
        body = html.escape(rendered)
        if len(body) > self.MAX_MESSAGE_BODY:
            body = body[: self.MAX_MESSAGE_BODY - 1] + "…"

        header = (
            f"<b>{html.escape(record.levelname)}</b> · "
            f"<code>{html.escape(record.name)}</code>"
        )

        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.created))
        header += f"\n<code>{html.escape(timestamp)}</code>"

        text = f"{header}\n\n<pre>{body}</pre>"
        if len(text) > self.MAX_TELEGRAM_LENGTH:
            text = text[: self.MAX_TELEGRAM_LENGTH - 1] + "…"
        return text

    async def _send(self, text: str) -> None:
        await self._bot.send_message(
            self._chat_id,
            text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    def _on_future_done(
        self,
        future: Future,
        record: logging.LogRecord,
    ) -> None:
        if future.cancelled():
            return
        exc = future.exception()
        if exc:
            record.exc_info = (exc.__class__, exc, exc.__traceback__)
            self.handleError(record)

    def _on_task_done(self, task: asyncio.Task, record: logging.LogRecord) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            record.exc_info = (exc.__class__, exc, exc.__traceback__)
            self.handleError(record)

    def _allow_throughput(self) -> bool:
        now = time.monotonic()
        while (
            self._sent_timestamps
            and now - self._sent_timestamps[0] > self._throttling_window
        ):
            self._sent_timestamps.popleft()
        limit = self._sent_timestamps.maxlen or 0
        if limit <= 0:
            return True
        return len(self._sent_timestamps) < limit

    def _should_dedupe(self, text: str) -> bool:
        if not self._last_text:
            return False
        if text != self._last_text:
            return False
        return (time.monotonic() - self._last_sent_at) < self._dedupe_window
