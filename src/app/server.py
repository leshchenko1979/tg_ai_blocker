import asyncio
import logging
import time
import traceback
from asyncio import TimeoutError

import logfire
from aiohttp import web

from .common.bot import LESHCHENKO_CHAT_ID, bot
from .common.llms import RateLimitExceeded
from .common.mp import mp
from .common.utils import remove_lines_to_fit_len
from .handlers.dp import dp

logger = logging.getLogger(__name__)

routes = web.RouteTableDef()
app = web.Application()

# Telegram webhook timeout is 60 seconds
# We'll use 55 seconds as our timeout to have some buffer
WEBHOOK_TIMEOUT = 55


@routes.post("/")
@routes.get("/")
async def handle_update(request: web.Request):
    if not await request.read():
        return web.Response()

    json = await request.json()
    start_time = time.time()

    with logfire.span("Update: handling...", update=json) as span:
        try:
            # Wrap the update handling in a timeout
            result = await asyncio.wait_for(
                dp.feed_raw_update(bot, json), timeout=WEBHOOK_TIMEOUT
            )
            span.message = f"Update handled: {result}"
            span.set_attribute("result", result)
            return web.json_response({"message": "Processed successfully"})

        except TimeoutError:
            elapsed = time.time() - start_time
            logger.warning(f"Webhook processing timed out after {elapsed:.2f} seconds")

            # Extract chat_id and admin_id for tracking
            chat_id = None
            admin_id = None
            for key in json:
                if isinstance(json[key], dict):
                    if "chat" in json[key]:
                        chat_id = json[key]["chat"]["id"]
                    if "from" in json[key]:
                        admin_id = json[key]["from"]["id"]
                    if chat_id and admin_id:
                        break

            if admin_id:
                mp.track(
                    admin_id,
                    "webhook_timeout",
                    {
                        "chat_id": chat_id,
                        "elapsed_seconds": elapsed,
                    },
                )

            # Notify about timeout but return 200 to prevent retries
            text = (
                f"⚠️ Webhook timeout after {elapsed:.2f} seconds\n"
                f"Chat ID: {chat_id}\n"
                f"Admin ID: {admin_id}\n"
                "Update will not be retried."
            )
            asyncio.create_task(
                bot.send_message(
                    LESHCHENKO_CHAT_ID,
                    text,
                    parse_mode="markdown",
                )
            )
            return web.json_response({"message": "Processing timed out"})

        except RateLimitExceeded as e:
            # Check if we still have time for retries
            elapsed = time.time() - start_time
            remaining = WEBHOOK_TIMEOUT - elapsed

            if remaining < 5:  # If less than 5 seconds remaining
                logger.warning(
                    "Rate limit hit but no time for retries",
                    extra={
                        "elapsed": elapsed,
                        "remaining": remaining,
                        "reset_time": e.reset_time,
                    },
                )
                # Return 200 to prevent Telegram retries
                return web.json_response(
                    {
                        "message": "Rate limit hit but no time for retries",
                        "elapsed": elapsed,
                    }
                )

            # We have time for retries, return 503
            logger.info(
                f"Rate limit exceeded, {remaining:.2f} seconds remaining for retries",
                extra={"reset_time": e.reset_time},
            )
            return web.json_response(
                {"error": "Rate limit exceeded", "retry_after": e.reset_time},
                status=503,
            )

        except Exception as e:
            # Extract chat_id and admin_id from any part of the incoming json by iterating its keys
            chat_id = None
            admin_id = None
            for key in json:
                if isinstance(json[key], dict):
                    if "chat" in json[key]:
                        chat_id = json[key]["chat"]["id"]
                    if "from" in json[key]:
                        admin_id = json[key]["from"]["id"]
                    if chat_id and admin_id:
                        break

            if admin_id:
                mp.track(
                    admin_id,
                    "unhandled_exception",
                    {"chat_id": chat_id, "exception": str(e)},
                )

            span.record_exception(e)

            text = f"Bot error: `{e}`\n```\n{traceback.format_exc()}\n```"
            asyncio.create_task(
                bot.send_message(
                    LESHCHENKO_CHAT_ID,
                    remove_lines_to_fit_len(text, 4096),
                    parse_mode="markdown",
                )
            )

            return web.json_response({"message": "Error processing request"})


app.add_routes(routes)
