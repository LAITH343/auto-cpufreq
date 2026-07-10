from dataclasses import dataclass, field
from typing import Optional

from auto_cpufreq.policy.profile import CHARGER


@dataclass
class PlatformFacts:
    """Sysfs-derived facts a decision needs. Gathered by platform/, never read here."""
    epp_supported: bool
    intel_pstate_present: bool
    amd_pstate_present: bool
    dynboost_enabled: bool
    active_pstate_status: Optional[str]  # intel_pstate/status or amd_pstate/status


@dataclass
class EppDecision:
    epp: Optional[str]
    messages: list[str] = field(default_factory=list)


def decide_epp(profile: str, governor: str, configured_epp: Optional[str], facts: PlatformFacts) -> EppDecision:
    if not facts.epp_supported:
        return EppDecision(None, ["Not setting EPP (not supported by system)"])

    if profile != CHARGER:
        if facts.dynboost_enabled:
            return EppDecision(None, ["Not setting EPP (dynamic boosting is enabled)"])
        epp = configured_epp if configured_epp is not None else "balance_power"
        return EppDecision(epp, [f'Setting to use: "{epp}" EPP'])

    # charger profile
    if facts.intel_pstate_present and facts.dynboost_enabled:
        return EppDecision(None, ["Not setting EPP (dynamic boosting is enabled)"])

    if not (facts.intel_pstate_present or facts.amd_pstate_present):
        return EppDecision(None, [])

    active = facts.active_pstate_status == "active"

    if configured_epp is not None:
        epp = configured_epp
        messages = []
        if active and epp != "performance" and governor == "performance":
            messages.append(f'Warning "{epp}" EPP cannot be used in performance governor')
            messages.append('Overriding EPP to "performance"')
            epp = "performance"
        messages.append(f'Setting to use: "{epp}" EPP')
        return EppDecision(epp, messages)

    epp = "performance" if active else "balance_performance"
    return EppDecision(epp, [f'Setting to use: "{epp}" EPP'])


def decide_epb(profile: str, configured_epb: Optional[str], intel_pstate_present: bool) -> tuple[Optional[str], str]:
    if not intel_pstate_present:
        return None, "Not setting EPB (not supported by system)"
    epb = configured_epb if configured_epb is not None else ("balance_performance" if profile == CHARGER else "balance_power")
    return epb, f'Setting to use: "{epb}" EPB'


def decide_governor(profile: str, configured_governor: Optional[str], available_governors_sorted: tuple) -> str:
    if configured_governor is not None:
        return configured_governor
    return available_governors_sorted[0] if profile == CHARGER else available_governors_sorted[-1]


@dataclass(frozen=True)
class PlatformProfileState:
    last_applied: dict = field(default_factory=dict)  # profile -> platform_profile value
    last_applied_section: Optional[str] = None


@dataclass
class PlatformProfileDecision:
    should_set: bool
    value: Optional[str]
    messages: list[str] = field(default_factory=list)


def is_platform_profile_enforced(conf, profile: str) -> tuple[bool, Optional[str]]:
    try:
        return conf.getboolean(profile, "enforce_platform_profile", fallback=True), None
    except ValueError:
        raw_value = conf[profile].get("enforce_platform_profile", "")
        return True, (
            f"Invalid boolean value for 'enforce_platform_profile' in profile '{profile}': "
            f"{raw_value!r}. Using default value True."
        )


def decide_platform_profile(conf, profile: str, platform_profile_supported: bool, state: PlatformProfileState) -> PlatformProfileDecision:
    if not conf.has_option(profile, "platform_profile"):
        return PlatformProfileDecision(False, None, [])

    if not platform_profile_supported:
        return PlatformProfileDecision(False, None, ["Not setting Platform Profile (not supported by system)"])

    pp = conf[profile]["platform_profile"]
    enforced, warning = is_platform_profile_enforced(conf, profile)
    messages = [warning] if warning else []

    if (
        not enforced
        and state.last_applied_section == profile
        and state.last_applied.get(profile) == pp
    ):
        return PlatformProfileDecision(False, None, messages)

    messages.append(f'Setting to use: "{pp}" Platform Profile')
    return PlatformProfileDecision(True, pp, messages)


class FrequencyConfigError(Exception):
    pass


@dataclass
class FrequencyDecision:
    min_value: int
    max_value: int


def decide_frequencies(conf, profile: str, min_limit: int, max_limit: int) -> FrequencyDecision:
    values = {}
    for key, default in (("scaling_min_freq", min_limit), ("scaling_max_freq", max_limit)):
        if conf.has_option(profile, key):
            raw_value = conf[profile][key].strip()
            try:
                value = int(raw_value)
            except ValueError:
                raise FrequencyConfigError(f"Invalid value for '{key}': {raw_value}")
        else:
            value = default

        if not min_limit <= value <= max_limit:
            raise FrequencyConfigError(
                f"Given value for '{key}' is not within the allowed frequencies {min_limit}-{max_limit} kHz"
            )
        values[key] = value

    return FrequencyDecision(min_value=values["scaling_min_freq"], max_value=values["scaling_max_freq"])
