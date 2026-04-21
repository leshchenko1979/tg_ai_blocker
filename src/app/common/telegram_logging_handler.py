import asyncio
import html
import logging
import threading
import time
from collections import deque
from typing import Deque, Optional

from aiogram import Bot


class TelegramLogHandler(logging.Handler):
    """
    Logging handler that forwards warnings and errors to a Telegram chat.

    Uses a queue-based approach with a background task to send messages,
    avoiding threading issues. Messages are throttled to avoid spamming.
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
        self._message_queue: Deque[str] = deque(maxlen=100)
        self._sent_timestamps: Deque[float] = deque(maxlen=throttling_capacity)
        self._throttling_window = throttling_window
        self._dedupe_window = dedupe_window
        self._last_text: Optional[str] = None
        self._last_sent_at: float = 0.0
        self._send_task: Optional[asyncio.Task] = None
        self._shutdown_flag = False

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """
        Register an asyncio loop and start the background send task.
        """
        with self._lock:
            self._loop = loop
            if self._send_task is None or self._send_task.done():
                self._send_task = loop.create_task(self._process_queue())

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
                # Buffer messages until loop is available
                self._message_queue.append(text)
                return

            # Bypass throttling for ERROR and CRITICAL level messages (keep deduplication)
            bypass_throttling = record.levelno >= logging.ERROR

            if self._should_dedupe(text):
                return

            if not bypass_throttling and not self._allow_throughput():
                return

            now = time.monotonic()
            self._last_text = text
            self._last_sent_at = now
            if not bypass_throttling:
                self._sent_timestamps.append(now)

            self._message_queue.append(text)

    async def _process_queue(self) -> None:
        """Background task that processes the message queue."""
        while not self._shutdown_flag:
            text = None
            with self._lock:
                if self._shutdown_flag:
                    break
                if self._message_queue:
                    text = self._message_queue.popleft()

            if text is not None:
                await self._send(text)
            else:
                await asyncio.sleep(0.1)

        # Drain remaining queued messages before exiting
        drain_logger = logging.getLogger(__name__)
        drained_count = 0
        while True:
            with self._lock:
                if not self._message_queue:
                    break
                text = self._message_queue.popleft()
            # Send outside the lock so emit() isn't blocked while we await
            try:
                await self._send(text)
                drained_count += 1
            except Exception as e:
                drain_logger.warning(
                    f"TelegramLogHandler _process_queue drain stopped after {drained_count} "
                    f"messages due to error: {e}",
                    exc_info=e,
                )
                break

    async def stop(self, timeout: float = 5.0) -> None:
        """
        Stop the background task gracefully.

        Args:
            timeout: Maximum time to wait for task completion in seconds
        """
        with self._lock:
            self._shutdown_flag = True
            task = self._send_task

        if task and not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=timeout)
            except asyncio.TimeoutError:
                logger = logging.getLogger(__name__)
                logger.warning(
                    f"TelegramLogHandler stop() timed out after {timeout}s, task may not have completed"
                )
            except asyncio.CancelledError:
                # Task was cancelled, which is expected
                pass

        # Best-effort drain of any remaining messages after task completes/times out.
        # This ensures messages are sent even if the task was cancelled or timed out.
        drain_logger = logging.getLogger(__name__)
        drained_count = 0
        while True:
            with self._lock:
                if not self._message_queue:
                    break
                text = self._message_queue.popleft()
            try:
                await self._send(text)
                drained_count += 1
            except Exception as e:
                drain_logger.warning(
                    f"TelegramLogHandler drain stopped early after {drained_count} messages "
                    f"due to error: {e}",
                    exc_info=e,
                )
                break

        self._send_task = None

    def _render_message(self, record: logging.LogRecord) -> str:
        rendered = self.format(record)
        body = html.escape(rendered)
        if len(body) > self.MAX_MESSAGE_BODY:
            body = f"{body[: self.MAX_MESSAGE_BODY - 1]}…"
        text = f"<pre>{body}</pre>"
        if len(text) > self.MAX_TELEGRAM_LENGTH:
            text = f"{text[: self.MAX_TELEGRAM_LENGTH - 1]}…"
        return text

    async def _send(self, text: str) -> None:
        await self._bot.send_message(
            self._chat_id,
            text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    def _allow_throughput(self) -> bool:
        now = time.monotonic()
        while (
            self._sent_timestamps
            and now - self._sent_timestamps[0] > self._throttling_window
        ):
            self._sent_timestamps.popleft()
        limit = self._sent_timestamps.maxlen or 0
        return True if limit <= 0 else len(self._sent_timestamps) < limit

    def _should_dedupe(self, text: str) -> bool:
        if not self._last_text:
            return False
        if text != self._last_text:
            return False
        return (time.monotonic() - self._last_sent_at) < self._dedupe_window
