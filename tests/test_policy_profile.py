import pytest

from auto_cpufreq.policy.profile import BATTERY, CHARGER, decide_profile


@pytest.mark.parametrize(
    "override,is_charging,expected",
    [
        ("default", True, CHARGER),
        ("default", False, BATTERY),
        ("powersave", True, BATTERY),
        ("powersave", False, BATTERY),
        ("performance", True, CHARGER),
        ("performance", False, CHARGER),
    ],
)
def test_decide_profile(override, is_charging, expected):
    assert decide_profile(override, is_charging) == expected
