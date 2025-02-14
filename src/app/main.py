# autoflake: skip_file

# Initialize environment variables
import dotenv

dotenv.load_dotenv()

# Initialize logging
import logging

from .logging_setup import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

# Start the server
from aiohttp import web

# Import all handlers to register them with the dispatcher
from .handlers import *
from .server import app  # noqa

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=8080)
