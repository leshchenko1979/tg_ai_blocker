import functools
import os

from mixpanel import Mixpanel

from .yandex_logging import get_yandex_logger

logger = get_yandex_logger(__name__)


class SilentMixpanel:
    def __init__(self, token: str = None):
        pass

    def track(self, user_id: int, event: str, properties: dict = None):
        pass


mp = Mixpanel(os.getenv("MIXPANEL_PROJECT_TOKEN"))


def track_with_error_handling(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in mp.track: {e}", exc_info=True)
            # Optionally, you can add more error handling logic here

    return wrapper


mp.track = track_with_error_handling(mp.track)


def mute_mp_for_tests():
    global mp
    mp = SilentMixpanel()
