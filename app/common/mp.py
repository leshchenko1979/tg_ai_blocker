import os

"""
from mixpanel import Mixpanel
"""


class Mixpanel:
    def __init__(self, token: str):
        pass

    def track(self, user_id: int, event: str, properties: dict):
        pass


mp = Mixpanel(os.getenv("MIXPANEL_PROJECT_TOKEN"))
