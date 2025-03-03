import asyncio
import logging
import time
import traceback
from asyncio import TimeoutError
from typing import Optional, Tuple, Union

import logfire
from aiogram.dispatcher.event.bases import UNHANDLED
from aiohttp import web

from .common.bot import LESHCHENKO_CHAT_ID, bot
from .common.llms import LocationNotSupported, RateLimitExceeded
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
async def handle_update(request: web.Request) -> web.Response:
    """Handle incoming Telegram update"""
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
            # Add tag based on handler result
            if result == UNHANDLED:
                span.tags = ["unhandled"]
            elif result:
                span.tags = [result]
            return web.json_response({"message": "Processed successfully"})

        except TimeoutError:
            elapsed = time.time() - start_time
            return await handle_timeout(span, json, elapsed)

        except (RateLimitExceeded, LocationNotSupported) as e:
            elapsed = time.time() - start_time
            remaining = WEBHOOK_TIMEOUT - elapsed
            return await handle_temporary_error(span, e, elapsed, remaining)

        except Exception as e:
            return await handle_unhandled_exception(span, e, json)


app.add_routes(routes)


def extract_ids_from_update(json: dict) -> Tuple[Optional[int], Optional[int]]:
    """Extract chat_id and admin_id from update"""
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
    return chat_id, admin_id


async def handle_timeout(
    span: logfire.LogfireSpan, json: dict, elapsed: float
) -> web.Response:
    """Handle timeout error"""
    logger.warning(f"Webhook processing timed out after {elapsed:.2f} seconds")
    span.tags = ["webhook_timeout"]

    chat_id, admin_id = extract_ids_from_update(json)

    if admin_id:
        mp.track(
            admin_id,
            "webhook_timeout",
            {
                "chat_id": chat_id,
                "elapsed_seconds": elapsed,
            },
        )

    text = (
        f"⚠️ Webhook timeout after {elapsed:.2f} seconds\n"
        f"Chat ID: {chat_id}\n"
        f"Admin ID: {admin_id}\n"
        "Update will be retried."
    )
    asyncio.create_task(
        bot.send_message(
            LESHCHENKO_CHAT_ID,
            text,
            parse_mode="markdown",
        )
    )
    return web.json_response(
        {"error": "Processing timed out", "retry": True},
        status=503,
    )


async def handle_temporary_error(
    span: logfire.LogfireSpan,
    e: Union[RateLimitExceeded, LocationNotSupported],
    elapsed: float,
    remaining: float,
) -> web.Response:
    """Handle rate limit or location not supported error"""
    error_type = (
        "rate_limit" if isinstance(e, RateLimitExceeded) else "location_not_supported"
    )
    span.tags = [error_type]

    if remaining < 5:  # If less than 5 seconds remaining
        error_type_msg = (
            "Rate limit"
            if isinstance(e, RateLimitExceeded)
            else "Location not supported"
        )
        logger.warning(
            f"{error_type_msg} hit but no time for retries",
            extra={
                "elapsed": elapsed,
                "remaining": remaining,
                "reset_time": getattr(e, "reset_time", None),
                "provider": getattr(e, "provider", None),
            },
        )
        return web.json_response(
            {
                "message": f"{error_type_msg} hit but no time for retries",
                "elapsed": elapsed,
            }
        )

    # We have time for retries, return 503
    if isinstance(e, RateLimitExceeded):
        # Если это ошибка от upstream-провайдера, возвращаем 503 без retry_after
        if e.is_upstream_error:
            logger.info(
                "Upstream provider rate limit exceeded, immediate retry",
                extra={"remaining": remaining},
            )
            return web.json_response(
                {"error": "Upstream provider rate limit exceeded"},
                status=503,
            )
        # Если это ошибка от OpenRouter, возвращаем 503 с retry_after
        else:
            logger.info(
                f"OpenRouter rate limit exceeded, {remaining:.2f} seconds remaining for retries",
                extra={"reset_time": e.reset_time},
            )
            return web.json_response(
                {
                    "error": "OpenRouter rate limit exceeded",
                    "retry_after": e.reset_time,
                },
                status=503,
            )
    else:  # LocationNotSupported
        logger.info(
            f"Location not supported for provider {e.provider}, {remaining:.2f} seconds remaining for retries"
        )
        return web.json_response(
            {"error": "Location not supported", "provider": e.provider},
            status=503,
        )


async def handle_unhandled_exception(
    span: logfire.LogfireSpan, e: Exception, json: dict
) -> web.Response:
    """Handle any unhandled exception"""
    span.tags = ["unhandled_exception"]
    span.record_exception(e)

    chat_id, admin_id = extract_ids_from_update(json)

    if admin_id:
        mp.track(
            admin_id,
            "unhandled_exception",
            {"chat_id": chat_id, "exception": str(e)},
        )

    text = f"Bot error: `{e}`\n```\n{traceback.format_exc()}\n```"
    asyncio.create_task(
        bot.send_message(
            LESHCHENKO_CHAT_ID,
            remove_lines_to_fit_len(text, 4096),
            parse_mode="markdown",
        )
    )

    return web.json_response({"message": "Error processing request"})
