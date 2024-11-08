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
    logger.setLevel(logging.DEBUG)
    return logger


def log_function_call(logger):
    """Декоратор для логирования вызовов функций с возможностью передачи логгера"""

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            logger.debug(
                f"Calling {func.__name__} with args: {args}, {kwargs}",
                extra={
                    "func_name": func.__name__,
                    "func_args": args,
                    "func_kwargs": kwargs,
                },
            )
            return await func(*args, **kwargs)

        return wrapper

    return decorator
