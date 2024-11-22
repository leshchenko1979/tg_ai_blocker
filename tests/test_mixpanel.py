from common.mp import SilentMixpanel, mp


def test_mp_is_silent():
    assert isinstance(mp, SilentMixpanel)
