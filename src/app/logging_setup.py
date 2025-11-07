import logging
import os

from .common.bot import LESHCHENKO_CHAT_ID, bot
from .common.telegram_logging_handler import TelegramLogHandler

debug = False
_telegram_handler: TelegramLogHandler | None = None


def mute_logging_for_tests():
    """Disable Logfire/Telegram logging side effects when running the test suite.

    Tests can alternatively set the ``SKIP_LOGFIRE`` environment variable to one of
    ``{"1", "true", "yes", "on"}`` to achieve the same effect without calling
    this helper explicitly.
    """
    global debug
    debug = True


def _should_skip_logfire() -> bool:
    """Determine whether Logfire initialization should be skipped for this process."""
    if debug:
        return True

    skip_env = os.getenv("SKIP_LOGFIRE", "").strip().lower()
    if skip_env in {"1", "true", "yes", "on"}:
        return True

    if "PYTEST_CURRENT_TEST" in os.environ:
        return True

    return False


def setup_logging():
    global _telegram_handler
    if _should_skip_logfire():
        logging.basicConfig(level=logging.DEBUG)
        return

    if not debug:
        # Initialize Logfire
        import logfire

        logfire.configure()

        _telegram_handler = TelegramLogHandler(bot=bot, chat_id=LESHCHENKO_CHAT_ID)
        _telegram_handler.setFormatter(
            logging.Formatter(
                "[%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
            )
        )

        logging.basicConfig(
            handlers=[logfire.LogfireLoggingHandler(), _telegram_handler],
            level=logging.DEBUG,
        )
        logfire.install_auto_tracing(
            modules=["app.database", "app.handlers"],
            min_duration=0.01,
            check_imported_modules="ignore",
        )


def register_telegram_logging_loop(loop):
    if _telegram_handler:
        _telegram_handler.set_event_loop(loop)


# Silence known chatty loggers
CHATTY_LOGGERS = [
    "hpack.hpack",
    "httpcore.http2",
    "httpcore.connection",
    "aiohttp.access",
]
for logger_name in CHATTY_LOGGERS:
    logging.getLogger(logger_name).setLevel(logging.WARNING)
