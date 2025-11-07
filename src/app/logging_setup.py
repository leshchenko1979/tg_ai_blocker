import logging

from .common.bot import LESHCHENKO_CHAT_ID, bot
from .common.telegram_logging_handler import TelegramLogHandler

debug = False
_telegram_handler: TelegramLogHandler | None = None


def mute_logging_for_tests():
    global debug
    debug = True


def setup_logging():
    global _telegram_handler
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
