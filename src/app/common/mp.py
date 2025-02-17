import logging
import os

from mixpanel import Mixpanel

logger = logging.getLogger(__name__)


class SilentMixpanel:
    def __init__(self, token: str = ""):
        pass

    def track(self, user_id: int, event: str, properties: dict | None = None):
        pass

    def people_set(self, user_id: int, properties: dict | None = None):
        pass

    def people_increment(self, user_id: int, properties: dict | None = None):
        pass


mp = Mixpanel(os.getenv("MIXPANEL_PROJECT_TOKEN"))


def mute_mp_for_tests():
    global mp
    mp = SilentMixpanel()
