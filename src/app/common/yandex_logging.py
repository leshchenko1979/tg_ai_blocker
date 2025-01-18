import functools
import inspect
import logging
import os

import logfire
from pythonjsonlogger import jsonlogger


class YandexFormatter(jsonlogger.JsonFormatter):
    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        log_record["logger"] = record.name
        log_record["level"] = record.levelname.replace("WARNING", "WARN").replace(
            "CRITICAL", "FATAL"
        )
        del log_record["levelname"]
        del log_record["name"]

    def format(self, record):
        return super().format(record).replace("\n", "\r")


yandex_handler = logging.StreamHandler()
yandex_handler.setFormatter(YandexFormatter("[%(levelname)s] %(name)s: %(message)s"))


debug = False


def mute_yandex_logging_for_tests():
    global debug
    debug = True


root_logger = logging.getLogger()


def setup_yandex_logging():
    if not debug:
        # Initialize Logfire
        if os.getenv("LOGFIRE_TOKEN"):
            logfire.configure()
            root_logger.addHandler(logfire.LogfireLoggingHandler())

        root_logger.addHandler(yandex_handler)
        root_logger.setLevel(logging.TRACE)


def get_yandex_logger(name):
    logger = logging.getLogger(name)

    if not debug:
        logger.setLevel(logging.TRACE)
        logger.propagate = False
        logger.addHandler(logfire.LogfireLoggingHandler())
        logger.addHandler(yandex_handler)

    return logger


def addLoggingLevel(levelName, levelNum, methodName=None):
    """
    Comprehensively adds a new logging level to the `logging` module and the
    currently configured logging class.

    `levelName` becomes an attribute of the `logging` module with the value
    `levelNum`. `methodName` becomes a convenience method for both `logging`
    itself and the class returned by `logging.getLoggerClass()` (usually just
    `logging.Logger`). If `methodName` is not specified, `levelName.lower()` is
    used.

    To avoid accidental clobberings of existing attributes, this method will
    raise an `AttributeError` if the level name is already an attribute of the
    `logging` module or if the method name is already present

    Example
    -------
    >>> addLoggingLevel('TRACE', logging.DEBUG - 5)
    >>> logging.getLogger(__name__).setLevel("TRACE")
    >>> logging.getLogger(__name__).trace('that worked')
    >>> logging.trace('so did this')
    >>> logging.TRACE
    5

    """
    if not methodName:
        methodName = levelName.lower()

    if hasattr(logging, levelName):
        raise AttributeError("{} already defined in logging module".format(levelName))
    if hasattr(logging, methodName):
        raise AttributeError("{} already defined in logging module".format(methodName))
    if hasattr(logging.getLoggerClass(), methodName):
        raise AttributeError("{} already defined in logger class".format(methodName))

    # This method was inspired by the answers to Stack Overflow post
    # http://stackoverflow.com/q/2183233/2988730, especially
    # http://stackoverflow.com/a/13638084/2988730
    def logForLevel(self, message, *args, **kwargs):
        if self.isEnabledFor(levelNum):
            self._log(levelNum, message, args, **kwargs)

    def logToRoot(message, *args, **kwargs):
        logging.log(levelNum, message, *args, **kwargs)

    logging.addLevelName(levelNum, levelName)
    setattr(logging, levelName, levelNum)
    setattr(logging.getLoggerClass(), methodName, logForLevel)
    setattr(logging, methodName, logToRoot)


addLoggingLevel("TRACE", logging.DEBUG - 5)


def log_function_call(logger_or_func=None):
    """Универсальный декоратор для логирования.
    Может использоваться:
    1. С явно переданным logger: @log_function_call(logger)
    2. Для методов класса: @log_function_call
    3. Для функций без логгера: @log_function_call
    """
    logfire_enabled = bool(os.getenv("LOGFIRE_TOKEN"))

    # If Logfire is enabled, use its built-in instrumentation
    if logfire_enabled:
        if callable(logger_or_func):
            return logfire.instrument()(logger_or_func)

        def wrapper(func):
            return logfire.instrument()(func)

        return wrapper

    # Otherwise use traditional logging
    def get_logger(self_or_none, explicit_logger) -> logging.Logger:
        if explicit_logger and isinstance(explicit_logger, logging.Logger):
            return explicit_logger
        if self_or_none and hasattr(self_or_none, "logger"):
            return self_or_none.logger
        return root_logger  # Используем root логгер по умолчанию

    def decorator(func):
        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                # Определяем logger
                is_method = args and hasattr(args[0], "logger")
                current_logger = get_logger(
                    args[0] if is_method else None,
                    logger_or_func
                    if isinstance(logger_or_func, logging.Logger)
                    else None,
                )

                current_logger.trace(
                    f"Calling {func.__name__}",
                    extra={
                        "func_name": func.__name__,
                        "func_args": args[1:] if is_method else args,
                        "func_kwargs": kwargs,
                    },
                )
                try:
                    result = await func(*args, **kwargs)
                    current_logger.trace(
                        f"{func.__name__} completed successfully",
                        extra={"func_name": func.__name__, "result": result},
                    )
                    return result
                except Exception as e:
                    current_logger.error(
                        f"{func.__name__} failed: {str(e)}",
                        extra={"func_name": func.__name__, "error": str(e)},
                        exc_info=True,
                    )
                    raise

            return async_wrapper
        else:

            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                # Определяем logger
                is_method = args and hasattr(args[0], "logger")
                current_logger = get_logger(
                    args[0] if is_method else None,
                    logger_or_func
                    if isinstance(logger_or_func, logging.Logger)
                    else None,
                )

                current_logger.trace(
                    f"Calling {func.__name__}",
                    extra={
                        "func_name": func.__name__,
                        "func_args": args[1:] if is_method else args,
                        "func_kwargs": kwargs,
                    },
                )
                try:
                    result = func(*args, **kwargs)
                    current_logger.trace(
                        f"{func.__name__} completed successfully",
                        extra={"func_name": func.__name__, "result": result},
                    )
                    return result
                except Exception as e:
                    current_logger.error(
                        f"{func.__name__} failed: {str(e)}",
                        extra={"func_name": func.__name__, "error": str(e)},
                        exc_info=True,
                    )
                    raise

            return sync_wrapper

    return decorator(logger_or_func) if callable(logger_or_func) else decorator


# Silence known chatty loggers
CHATTY_LOGGERS = ["hpack.hpack", "httpcore.http2", "httpcore.connection"]
for logger_name in CHATTY_LOGGERS:
    logging.getLogger(logger_name).setLevel(logging.WARNING)
