import os

from mixpanel import Mixpanel


class SilentMixpanel:
    def __init__(self, token: str):
        pass

    def track(self, user_id: int, event: str, properties: dict):
        pass


# silent if pytest is running
mp = (
    Mixpanel(os.getenv("MIXPANEL_PROJECT_TOKEN"))
    if not os.environ.get("PYTEST_CURRENT_TEST")
    else SilentMixpanel()
)
