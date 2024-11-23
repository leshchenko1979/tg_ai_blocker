# autoflake: skip_file

import dotenv
import uvicorn

from .common.yandex_logging import get_yandex_logger, setup_yandex_logging

# Initialize environment variables
dotenv.load_dotenv()

# Initialize logging
setup_yandex_logging()
logger = get_yandex_logger(__name__)
logger.trace("Logger initialized")
get_yandex_logger("aiogram")  # Initialize aiogram logger

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
from .server import app

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
