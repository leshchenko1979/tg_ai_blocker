# autoflake: skip_file

# Initialize logging
import logging

from .common.yandex_logging import get_yandex_logger, setup_yandex_logging

setup_yandex_logging()
logger = get_yandex_logger(__name__)
get_yandex_logger("aiogram").setLevel(logging.DEBUG)  # Initialize aiogram logger

logger.trace("Logger initialized")

# Import faster aiogram
from .faster_aiogram import bootstrap  # noqa

logger.trace("Faster aiogram imported")

# Initialize environment variables
import dotenv

dotenv.load_dotenv()

logger.trace("Environment variables loaded")

# Import all handlers to register them with the dispatcher
from .handlers import (  # noqa
    callback_handlers,
    command_handlers,
    message_handlers,
    payment_handlers,
    private_handlers,
    status_handlers,
)

logger.trace("Handlers imported")

# Start the server
from .server import app  # noqa

logger.trace("Server imported")

# if __name__ == "__main__":
#     uvicorn.run(app, host="0.0.0.0", port=8000)
