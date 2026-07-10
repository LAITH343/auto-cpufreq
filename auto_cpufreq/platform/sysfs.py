import os
from pathlib import Path
from typing import Optional

CPU_ROOT = Path("/sys/devices/system/cpu")
FIRMWARE_ROOT = Path("/sys/firmware")

# cpufreqctl.sh's EPB word -> raw energy_perf_bias value mapping
EPB_NAME_TO_VALUE = {
    "performance": 0,
    "balance_performance": 4,
    "default": 6,
    "balance_power": 8,
    "power": 15,
}


def _cpu_count() -> int:
    return os.cpu_count() or 1


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text().strip()
    except (FileNotFoundError, OSError):
        return None


def write_text(path: Path, value: str) -> bool:
    try:
        path.write_text(str(value))
        return True
    except (FileNotFoundError, OSError, PermissionError):
        return False


_read = read_text
_write = write_text


def _cpufreq_path(core: int, filename: str) -> Path:
    return CPU_ROOT / f"cpu{core}" / "cpufreq" / filename


def _power_path(core: int, filename: str) -> Path:
    return CPU_ROOT / f"cpu{core}" / "power" / filename


def scaling_driver() -> Optional[str]:
    return _read(_cpufreq_path(0, "scaling_driver"))


def available_governors() -> list[str]:
    value = _read(_cpufreq_path(0, "scaling_available_governors"))
    return value.split() if value else []


def get_governor() -> Optional[str]:
    return _read(_cpufreq_path(0, "scaling_governor"))


def set_governor(value: str) -> bool:
    ok = True
    for core in range(_cpu_count()):
        ok = _write(_cpufreq_path(core, "scaling_governor"), value) and ok
    return ok


def epp_supported() -> bool:
    return _cpufreq_path(0, "energy_performance_preference").exists()


def get_epp() -> Optional[str]:
    return _read(_cpufreq_path(0, "energy_performance_preference"))


def set_epp(value: str) -> bool:
    ok = True
    for core in range(_cpu_count()):
        ok = _write(_cpufreq_path(core, "energy_performance_preference"), value) and ok
    return ok


def intel_pstate_path() -> Path:
    return CPU_ROOT / "intel_pstate"


def epb_supported() -> bool:
    return intel_pstate_path().exists()


def get_epb() -> Optional[str]:
    return _read(_power_path(0, "energy_perf_bias"))


def set_epb(value: str) -> bool:
    if isinstance(value, str) and value.isdigit():
        raw = int(value)
    else:
        raw = EPB_NAME_TO_VALUE.get(value)
        if raw is None:
            return False
    if not (0 <= raw <= 15):
        return False
    ok = True
    for core in range(_cpu_count()):
        path = _power_path(core, "energy_perf_bias")
        if path.exists():
            ok = _write(path, str(raw)) and ok
    return ok


def platform_profile_supported() -> bool:
    return (FIRMWARE_ROOT / "acpi" / "platform_profile").exists()


def get_platform_profile() -> Optional[str]:
    return _read(FIRMWARE_ROOT / "acpi" / "platform_profile")


def set_platform_profile(value: str) -> bool:
    # skip redundant writes: rewriting the same profile can wake devices (e.g. NVIDIA GPUs)
    if get_platform_profile() == value:
        return True
    return _write(FIRMWARE_ROOT / "acpi" / "platform_profile", value)


def get_frequency_max() -> Optional[int]:
    value = _read(_cpufreq_path(0, "scaling_max_freq"))
    return int(value) if value else None


def get_frequency_min() -> Optional[int]:
    value = _read(_cpufreq_path(0, "scaling_min_freq"))
    return int(value) if value else None


def set_frequency_max(value: int) -> bool:
    ok = True
    for core in range(_cpu_count()):
        ok = _write(_cpufreq_path(core, "scaling_max_freq"), str(value)) and ok
    return ok


def set_frequency_min(value: int) -> bool:
    ok = True
    for core in range(_cpu_count()):
        ok = _write(_cpufreq_path(core, "scaling_min_freq"), str(value)) and ok
    return ok


def get_frequency_min_limit() -> Optional[int]:
    cpuinfo = _read(_cpufreq_path(0, "cpuinfo_min_freq"))
    scaling = _read(_cpufreq_path(0, "scaling_min_freq"))
    values = [int(v) for v in (cpuinfo, scaling) if v]
    return min(values) if values else None


def get_frequency_max_limit() -> Optional[int]:
    cpuinfo = _read(_cpufreq_path(0, "cpuinfo_max_freq"))
    scaling = _read(_cpufreq_path(0, "scaling_max_freq"))
    values = [int(v) for v in (cpuinfo, scaling) if v]
    return max(values) if values else None


def boost_path() -> Path:
    return CPU_ROOT / "cpufreq" / "boost"


def no_turbo_path() -> Path:
    return CPU_ROOT / "intel_pstate" / "no_turbo"


def amd_pstate_status_path() -> Path:
    return CPU_ROOT / "amd_pstate" / "status"


def get_amd_pstate_status() -> Optional[str]:
    return _read(amd_pstate_status_path())


def hwp_dynamic_boost_path() -> Path:
    return CPU_ROOT / "intel_pstate" / "hwp_dynamic_boost"


def hwp_dynamic_boost_enabled() -> bool:
    value = _read(hwp_dynamic_boost_path())
    return bool(int(value)) if value is not None else False


def intel_pstate_status_path() -> Path:
    return CPU_ROOT / "intel_pstate" / "status"


def intel_pstate_status() -> Optional[str]:
    return _read(intel_pstate_status_path())


def amd_pstate_path() -> Path:
    return CPU_ROOT / "amd_pstate"
