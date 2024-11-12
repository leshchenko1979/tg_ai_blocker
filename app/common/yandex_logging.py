import functools
import logging

from pythonjsonlogger import jsonlogger


class YandexFormatter(jsonlogger.JsonFormatter):
    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        log_record["logger"] = record.name
        log_record["level"] = record.levelname.replace("WARNING", "WARN").replace(
            "CRITICAL", "FATAL"
        )
        # del log_record["levelname"]
        # del log_record["name"]

    def format(self, record):
        return super().format(record).replace("\n", "\r")


yandex_handler = logging.StreamHandler()
yandex_handler.setFormatter(YandexFormatter("[%(levelname)s] %(name)s: %(message)s"))

# root_logger = logging.getLogger()
# root_logger.addHandler(yandex_handler)


def get_yandex_logger(name):
    logger = logging.getLogger(name)
    logger.propagate = False
    logger.addHandler(yandex_handler)
    logger.setLevel(logging.TRACE)
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


def log_function_call(logger: logging.Logger):
    """Декоратор для логирования вызовов функций с возможностью передачи логгера"""

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            logger.trace(
                f"Calling {func.__name__} with args: {args}, {kwargs}",
                extra={
                    "func_name": func.__name__,
                    "func_args": args,
                    "func_kwargs": kwargs,
                },
            )
            result = await func(*args, **kwargs)
            logger.trace(
                f"Function {func.__name__} returned {result}",
                extra={"func_result": result},
            )
            return result

        return wrapper

    return decorator
