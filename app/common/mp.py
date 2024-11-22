import os

from mixpanel import Mixpanel


class SilentMixpanel:
    def __init__(self, token: str = None):
        pass

    def track(self, user_id: int, event: str, properties: dict = None):
        pass


mp = Mixpanel(os.getenv("MIXPANEL_PROJECT_TOKEN"))


def mute_mp_for_tests():
    global mp
    mp = SilentMixpanel()
