from configparser import ConfigParser

import pytest

from auto_cpufreq.policy.profile import BATTERY, CHARGER
from auto_cpufreq.policy.settings import (
    FrequencyConfigError,
    PlatformFacts,
    PlatformProfileState,
    decide_epb,
    decide_epp,
    decide_frequencies,
    decide_governor,
    decide_platform_profile,
    is_platform_profile_enforced,
)


def facts(**overrides):
    base = dict(
        epp_supported=True,
        intel_pstate_present=False,
        amd_pstate_present=False,
        dynboost_enabled=False,
        active_pstate_status=None,
    )
    base.update(overrides)
    return PlatformFacts(**base)


def conf_with(section, **options):
    conf = ConfigParser()
    conf[section] = {k: str(v) for k, v in options.items()}
    return conf


# --- governor ---

def test_decide_governor_uses_config_value():
    assert decide_governor(CHARGER, "performance", ("performance", "powersave")) == "performance"


def test_decide_governor_default_charger_is_first_available():
    assert decide_governor(CHARGER, None, ("performance", "powersave")) == "performance"


def test_decide_governor_default_battery_is_last_available():
    assert decide_governor(BATTERY, None, ("performance", "powersave")) == "powersave"


# --- EPP ---

def test_epp_not_supported():
    d = decide_epp(CHARGER, "performance", None, facts(epp_supported=False))
    assert d.epp is None
    assert d.messages == ["Not setting EPP (not supported by system)"]


def test_epp_battery_dynboost_enabled():
    d = decide_epp(BATTERY, "powersave", None, facts(dynboost_enabled=True))
    assert d.epp is None
    assert "dynamic boosting" in d.messages[0]


def test_epp_battery_default_is_balance_power():
    d = decide_epp(BATTERY, "powersave", None, facts())
    assert d.epp == "balance_power"


def test_epp_battery_uses_configured_value_verbatim():
    d = decide_epp(BATTERY, "powersave", "power", facts())
    assert d.epp == "power"


def test_epp_charger_no_pstate_driver_present_is_untouched():
    d = decide_epp(CHARGER, "performance", None, facts())
    assert d.epp is None
    assert d.messages == []


def test_epp_charger_intel_active_defaults_to_performance():
    d = decide_epp(CHARGER, "performance", None, facts(intel_pstate_present=True, active_pstate_status="active"))
    assert d.epp == "performance"


def test_epp_charger_intel_passive_defaults_to_balance_performance():
    d = decide_epp(CHARGER, "performance", None, facts(intel_pstate_present=True, active_pstate_status="passive"))
    assert d.epp == "balance_performance"


def test_epp_charger_intel_active_overrides_incompatible_configured_epp():
    d = decide_epp(
        CHARGER, "performance", "balance_performance",
        facts(intel_pstate_present=True, active_pstate_status="active"),
    )
    assert d.epp == "performance"
    assert any("cannot be used" in m for m in d.messages)
    assert any("Overriding EPP" in m for m in d.messages)


def test_epp_charger_intel_active_but_governor_not_performance_keeps_configured_epp():
    d = decide_epp(
        CHARGER, "powersave", "balance_power",
        facts(intel_pstate_present=True, active_pstate_status="active"),
    )
    assert d.epp == "balance_power"
    assert d.messages == ['Setting to use: "balance_power" EPP']


def test_epp_charger_amd_active_defaults_to_performance():
    d = decide_epp(CHARGER, "performance", None, facts(amd_pstate_present=True, active_pstate_status="active"))
    assert d.epp == "performance"


def test_epp_charger_dynboost_only_suppresses_when_intel_present():
    # dynboost flag with no intel/amd present at all shouldn't happen in practice,
    # but intel_pstate_present gates the dynboost short-circuit specifically.
    d = decide_epp(CHARGER, "performance", None, facts(intel_pstate_present=True, dynboost_enabled=True))
    assert d.epp is None
    assert "dynamic boosting" in d.messages[0]


# --- EPB ---

def test_epb_not_supported_without_intel_pstate():
    epb, message = decide_epb(CHARGER, None, intel_pstate_present=False)
    assert epb is None
    assert message == "Not setting EPB (not supported by system)"


def test_epb_default_charger_is_balance_performance():
    epb, _ = decide_epb(CHARGER, None, intel_pstate_present=True)
    assert epb == "balance_performance"


def test_epb_default_battery_is_balance_power():
    epb, _ = decide_epb(BATTERY, None, intel_pstate_present=True)
    assert epb == "balance_power"


def test_epb_uses_configured_value():
    epb, _ = decide_epb(CHARGER, "power", intel_pstate_present=True)
    assert epb == "power"


# --- platform profile ---

def test_platform_profile_not_configured():
    conf = ConfigParser()
    conf["charger"] = {}
    d = decide_platform_profile(conf, "charger", True, PlatformProfileState())
    assert d.should_set is False


def test_platform_profile_unsupported_system():
    conf = conf_with("charger", platform_profile="balanced")
    d = decide_platform_profile(conf, "charger", False, PlatformProfileState())
    assert d.should_set is False
    assert "not supported" in d.messages[0]


def test_platform_profile_sets_when_enforced_every_tick():
    conf = conf_with("charger", platform_profile="balanced")
    state = PlatformProfileState(last_applied={"charger": "balanced"}, last_applied_section="charger")
    d = decide_platform_profile(conf, "charger", True, state)
    assert d.should_set is True  # enforce_platform_profile defaults to True
    assert d.value == "balanced"


def test_platform_profile_skips_when_not_enforced_and_unchanged():
    conf = conf_with("charger", platform_profile="balanced", enforce_platform_profile="false")
    state = PlatformProfileState(last_applied={"charger": "balanced"}, last_applied_section="charger")
    d = decide_platform_profile(conf, "charger", True, state)
    assert d.should_set is False


def test_platform_profile_reapplies_when_not_enforced_but_profile_switched():
    conf = conf_with("charger", platform_profile="balanced", enforce_platform_profile="false")
    state = PlatformProfileState(last_applied={"charger": "balanced"}, last_applied_section="battery")
    d = decide_platform_profile(conf, "charger", True, state)
    assert d.should_set is True


def test_platform_profile_invalid_enforce_value_warns_and_defaults_true():
    conf = conf_with("charger", platform_profile="balanced", enforce_platform_profile="not-a-bool")
    enforced, warning = is_platform_profile_enforced(conf, "charger")
    assert enforced is True
    assert "Invalid boolean value" in warning


# --- frequencies ---

def test_decide_frequencies_defaults_to_limits():
    conf = ConfigParser()
    conf["charger"] = {}
    d = decide_frequencies(conf, "charger", min_limit=800000, max_limit=4000000)
    assert d.min_value == 800000
    assert d.max_value == 4000000


def test_decide_frequencies_uses_configured_values():
    conf = conf_with("charger", scaling_min_freq=1000000, scaling_max_freq=3000000)
    d = decide_frequencies(conf, "charger", min_limit=800000, max_limit=4000000)
    assert d.min_value == 1000000
    assert d.max_value == 3000000


def test_decide_frequencies_rejects_non_integer():
    conf = conf_with("charger", scaling_max_freq="not-a-number")
    with pytest.raises(FrequencyConfigError):
        decide_frequencies(conf, "charger", min_limit=800000, max_limit=4000000)


def test_decide_frequencies_rejects_out_of_range():
    conf = conf_with("charger", scaling_max_freq=9000000)
    with pytest.raises(FrequencyConfigError):
        decide_frequencies(conf, "charger", min_limit=800000, max_limit=4000000)
