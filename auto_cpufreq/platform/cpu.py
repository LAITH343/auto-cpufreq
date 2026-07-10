from dataclasses import dataclass
from typing import Optional

from auto_cpufreq.platform import sysfs


@dataclass
class TurboControl:
    """Which sysfs file controls turbo, and whether its logic is inverted (0 = on)."""
    path: object
    inverse: bool


def detect_turbo_control() -> Optional[TurboControl]:
    if sysfs.no_turbo_path().exists():
        return TurboControl(path=sysfs.no_turbo_path(), inverse=True)
    if sysfs.boost_path().exists():
        return TurboControl(path=sysfs.boost_path(), inverse=False)
    return None


def get_turbo() -> Optional[bool]:
    """Current turbo state. None if not controllable on this system (including amd_pstate)."""
    control = detect_turbo_control()
    if control is not None:
        value = sysfs.read_text(control.path)
        if value is None:
            return None
        return bool(int(value)) ^ control.inverse
    if sysfs.amd_pstate_path().exists():
        # amd-pstate-epp manages turbo itself; not directly controllable here.
        return None
    return None


def set_turbo(value: bool) -> bool:
    control = detect_turbo_control()
    if control is None:
        return False
    return sysfs.write_text(control.path, f"{int(value ^ control.inverse)}\n")


def amd_pstate_active() -> bool:
    return sysfs.get_amd_pstate_status() == "active"


def turbo_controllable() -> bool:
    return detect_turbo_control() is not None


def is_intel_pstate() -> bool:
    return sysfs.epb_supported()


def is_amd_pstate() -> bool:
    return sysfs.amd_pstate_path().exists()


def epp_must_be_performance(governor: str) -> bool:
    """Intel/AMD *-pstate active-mode HWP forces EPP to 'performance' when the
    governor is 'performance' — writing anything else silently fails."""
    if governor != "performance":
        return False
    if is_intel_pstate():
        return sysfs.intel_pstate_status() == "active"
    if is_amd_pstate():
        return sysfs.get_amd_pstate_status() == "active"
    return False
