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
from .database.postgres_connection import close_pool
from .handlers.dp import dp
from .logging_setup import get_telegram_handler, register_telegram_logging_loop

logger = logging.getLogger(__name__)

routes = web.RouteTableDef()
app = web.Application()

# Telegram webhook timeout is 60 seconds
# We'll use 55 seconds as our timeout to have some buffer
WEBHOOK_TIMEOUT = 55


@routes.get("/health")
async def healthcheck(_: web.Request) -> web.Response:
    """Return plain OK response for health probes."""
    return web.Response(text="ok")


@routes.post("/")
@routes.get("/")
async def handle_update(request: web.Request) -> web.Response:
    """Handle incoming Telegram update"""
    if not await request.read():
        return web.Response()

    json = await request.json()

    # Validate that this is a proper Telegram update
    if not isinstance(json, dict) or "update_id" not in json:
        logger.warning(f"Received invalid update format: {json}")
        return web.json_response(
            {"error": "Invalid update format", "required_field": "update_id"},
            status=400,
        )

    start_time = time.time()

    with logfire.span("Update: handling...", update=json) as span:
        try:
            # Wrap the update handling in a timeout
            result = await asyncio.wait_for(
                dp.feed_raw_update(bot, json), timeout=WEBHOOK_TIMEOUT
            )

            # Extract message title or username from the update
            for path in ["message.chat.title", "message.from.username"]:
                try:
                    current = json
                    for part in path.split("."):
                        current = current[part]
                    span.message = f"{current}"
                    break
                except Exception:
                    continue
            else:
                span.message = "Unknown chat or user"

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


async def _on_startup_register_logging(app: web.Application) -> None:
    register_telegram_logging_loop(asyncio.get_running_loop())


async def _on_startup_setup_webhook(app: web.Application) -> None:
    """Set up Telegram webhook on startup"""
    try:
        webhook_url = "https://tg-ai-blocker.redevest.ru/"
        logger.info(f"Setting webhook URL to: {webhook_url}")
        await bot.set_webhook(webhook_url)
        logger.info("Webhook setup completed successfully")
    except Exception as e:
        logger.error(f"Failed to set webhook: {e}")
        raise


async def _on_startup_log_server_started(app: web.Application) -> None:
    logging.warning("Server started")


async def _shutdown(app: web.Application) -> None:
    """Gracefully shutdown all resources."""
    logger.warning("Starting graceful shutdown...")

    async with asyncio.TaskGroup() as tg:
        tg.create_task(bot.session.close())
        tg.create_task(close_pool())

    # Stop TelegramLogHandler background task last
    telegram_handler = get_telegram_handler()
    if telegram_handler:
        try:
            await telegram_handler.stop(timeout=5.0)
        except Exception as e:
            logger.warning(f"Error stopping TelegramLogHandler: {e}", exc_info=True)


app.on_startup.append(_on_startup_register_logging)
app.on_startup.append(_on_startup_setup_webhook)
app.on_startup.append(_on_startup_log_server_started)
app.on_shutdown.append(_shutdown)


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

    text = f"Bot error: <code>{e}</code>\n<pre>\n{traceback.format_exc()}\n</pre>"
    asyncio.create_task(
        bot.send_message(
            LESHCHENKO_CHAT_ID,
            remove_lines_to_fit_len(text, 4096),
            parse_mode="HTML",
        )
    )

    return web.json_response({"message": "Error processing request"})
