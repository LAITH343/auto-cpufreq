from __future__ import annotations

import os
import re
from pathlib import Path

from auto_cpufreq.battery_scripts.battery import get_battery_device
from auto_cpufreq.battery_scripts.ideapad_laptop import IdeapadBatteryDevice
from auto_cpufreq.config.config import config
from auto_cpufreq.core import normalize_epb_target, set_override, set_turbo_override
from auto_cpufreq.dbus.models import IGNORE_LIST_SECTION, PROFILE_SECTIONS, CapabilitiesModel, config_writable
from auto_cpufreq.globals import IS_INSTALLED_WITH_SNAP
from auto_cpufreq.power_helper import set_bluetooth_auto_enable

GOVERNOR_OVERRIDES = ("auto", "performance", "powersave")
TURBO_OVERRIDES = ("auto", "always", "never")
TURBO_MODES = ("auto", "always", "never")

PROFILE_KEYS = (
    "governor",
    "energy_performance_preference",
    "energy_perf_bias",
    "hwp_dynamic_boost",
    "platform_profile",
    "enforce_platform_profile",
    "scaling_min_freq",
    "scaling_max_freq",
    "turbo",
)
BATTERY_KEYS = (
    "battery_device",
    "enable_thresholds",
    "start_threshold",
    "stop_threshold",
    "ideapad_laptop_conservation_mode",
)


class ActionError(Exception):
    pass


class InvalidArgument(ActionError):
    pass


class NotSupported(ActionError):
    pass


def set_governor_override(value: str) -> None:
    if value not in GOVERNOR_OVERRIDES:
        raise InvalidArgument(f"Governor override must be one of: {', '.join(GOVERNOR_OVERRIDES)}")
    set_override("reset" if value == "auto" else value)


def set_turbo_override_mode(value: str) -> None:
    if value not in TURBO_OVERRIDES:
        raise InvalidArgument(f"Turbo override must be one of: {', '.join(TURBO_OVERRIDES)}")
    set_turbo_override(value)


def reset_overrides() -> None:
    set_override("reset")
    set_turbo_override("auto")


def set_config_section(path: str, section: str, values: dict[str, str]) -> None:
    """Set keys of [charger] or [battery]; an empty value removes the key."""
    _require_writable(path)
    if section not in PROFILE_SECTIONS:
        raise InvalidArgument(f"Section must be one of: {', '.join(PROFILE_SECTIONS)}")

    capabilities = CapabilitiesModel.read()
    changes = {}
    for key, value in values.items():
        if key not in PROFILE_KEYS:
            raise InvalidArgument(f"Unknown key for [{section}]: {key}")
        value = value.strip()
        changes[key] = _validate_profile_value(key, value, capabilities) if value else None

    _check_frequency_range(path, section, changes)
    ConfigFile(path).update_section(section, changes)


def set_ignore_list(path: str, names: list[str]) -> None:
    _require_writable(path)
    names = list(dict.fromkeys(name.strip() for name in names if name.strip()))
    for name in names:
        if "/" in name or "=" in name or name.startswith(("#", ";", "[")):
            raise InvalidArgument(f"Invalid power supply name: {name}")
    ConfigFile(path).replace_section(IGNORE_LIST_SECTION, {f"name{i}": name for i, name in enumerate(names, 1)})


def set_battery_config(path: str, values: dict[str, str]) -> None:
    """Set battery charging keys of [battery] and apply them right away."""
    _require_writable(path)
    capabilities = CapabilitiesModel.read()
    changes = {}
    for key, value in values.items():
        if key not in BATTERY_KEYS:
            raise InvalidArgument(f"Unknown battery key: {key}")
        value = value.strip()
        changes[key] = _validate_battery_value(key, value, capabilities) if value else None

    merged = {**ConfigFile(path).read_section("battery"), **changes}
    start, stop = merged.get("start_threshold"), merged.get("stop_threshold")
    if start and stop and start.isdigit() and stop.isdigit() and int(start) >= int(stop):
        raise InvalidArgument("Start threshold must be lower than stop threshold")

    ConfigFile(path).update_section("battery", changes)
    config.update_config()
    _apply_battery_settings()


def set_bluetooth_boot(enabled: bool) -> None:
    if IS_INSTALLED_WITH_SNAP:
        raise ActionError("Bluetooth on boot can't be changed from the snap package")
    if not set_bluetooth_auto_enable(enabled):
        raise ActionError("Unable to update /etc/bluetooth/main.conf")


def _require_writable(path: str) -> None:
    if not config_writable(path):
        raise NotSupported(f"{path} is read-only, editing the config via D-Bus is not supported here")


def _validate_profile_value(key: str, value: str, capabilities: CapabilitiesModel) -> str:
    if key == "governor":
        return _one_of(key, value, capabilities.governors)
    if key == "energy_performance_preference":
        return _one_of(key, value, capabilities.epp_choices)
    if key == "energy_perf_bias":
        if normalize_epb_target(value) is None:
            raise InvalidArgument("energy_perf_bias must be 0-15 or a named EPB value")
        return value
    if key == "platform_profile":
        return _one_of(key, value, capabilities.platform_profiles)
    if key == "turbo":
        return _one_of(key, value, TURBO_MODES)
    if key in ("hwp_dynamic_boost", "enforce_platform_profile"):
        return _one_of(key, value.lower(), ("true", "false"))

    frequency = _int_value(key, value)
    low, high = capabilities.hw_min_freq_khz, capabilities.hw_max_freq_khz
    if (low is not None and frequency < low) or (high is not None and frequency > high):
        raise InvalidArgument(f"{key} must be between {low} and {high} kHz")
    return str(frequency)


def _validate_battery_value(key: str, value: str, capabilities: CapabilitiesModel) -> str:
    if key == "battery_device":
        return _one_of(key, value, capabilities.batteries)
    if key in ("enable_thresholds", "ideapad_laptop_conservation_mode"):
        return _one_of(key, value.lower(), ("true", "false"))

    threshold = _int_value(key, value)
    low, high = (0, 99) if key == "start_threshold" else (1, 100)
    if not low <= threshold <= high:
        raise InvalidArgument(f"{key} must be between {low} and {high}")
    return str(threshold)


def _one_of(key: str, value: str, allowed) -> str:
    if value not in allowed:
        raise InvalidArgument(f"{key} must be one of: {', '.join(allowed) or 'nothing (not supported)'}")
    return value


def _int_value(key: str, value: str) -> int:
    if not value.isdigit():
        raise InvalidArgument(f"{key} must be a whole number")
    return int(value)


def _check_frequency_range(path: str, section: str, changes: dict[str, str | None]) -> None:
    current = ConfigFile(path).read_section(section)
    merged = {**current, **changes}
    low, high = merged.get("scaling_min_freq"), merged.get("scaling_max_freq")
    if low and high and low.isdigit() and high.isdigit() and int(low) >= int(high):
        raise InvalidArgument("scaling_min_freq must be lower than scaling_max_freq")


def _apply_battery_settings() -> None:
    device = get_battery_device()
    if device is None:
        return

    parsed = device.get_parsed_config()
    if parsed["thresholds_enabled"]:
        device.apply_threshold_settings()
    elif isinstance(device, IdeapadBatteryDevice):
        if device.conservation_mode_path:
            device.set_conservation_mode(0)
    else:
        for bat in device.batteries:
            device.set_battery_thresholds(bat, 0, 100)


class ConfigFile:
    """Line based editor for the auto-cpufreq config that keeps comments and layout."""

    SECTION = re.compile(r"^\s*\[([^\]]+)\]\s*$")

    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def _key_line(self, key: str) -> re.Pattern:
        return re.compile(rf"^\s*{re.escape(key)}\s*[=:]", re.IGNORECASE)

    def _commented_key_line(self, key: str) -> re.Pattern:
        return re.compile(rf"^\s*[#;]\s*{re.escape(key)}\s*[=:]", re.IGNORECASE)

    def _read_lines(self) -> list[str]:
        try:
            return self.path.read_text().splitlines(keepends=True)
        except FileNotFoundError:
            return []

    def _write_lines(self, lines: list[str]) -> None:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w") as f:
            f.writelines(lines)
        os.chmod(self.path, 0o644)

    def _section_bounds(self, lines: list[str], section: str) -> tuple[int, int] | None:
        start = None
        for i, line in enumerate(lines):
            match = self.SECTION.match(line)
            if not match:
                continue
            if start is not None:
                return start, i
            if match.group(1).strip() == section:
                start = i + 1
        return (start, len(lines)) if start is not None else None

    def _append_section(self, lines: list[str], section: str) -> tuple[int, int]:
        if lines and lines[-1].strip():
            lines.append("\n")
        lines.append(f"[{section}]\n")
        return len(lines), len(lines)

    def read_section(self, section: str) -> dict[str, str]:
        lines = self._read_lines()
        bounds = self._section_bounds(lines, section)
        values = {}
        if bounds is None:
            return values
        for line in lines[bounds[0]:bounds[1]]:
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", ";")):
                continue
            match = re.match(r"^([^=:]+)[=:](.*)$", stripped)
            if match:
                values[match.group(1).strip().lower()] = match.group(2).strip()
        return values

    def update_section(self, section: str, changes: dict[str, str | None]) -> None:
        """Set keys to the given values; None comments the key out."""
        if not changes:
            return
        lines = self._read_lines()
        bounds = self._section_bounds(lines, section)
        if bounds is None:
            if all(value is None for value in changes.values()):
                return
            bounds = self._append_section(lines, section)

        for key, value in changes.items():
            start, end = bounds
            active = next((i for i in range(start, end) if self._key_line(key).match(lines[i])), None)

            if value is None:
                if active is not None:
                    lines[active] = f"# {lines[active].lstrip()}"
                continue

            new_line = f"{key} = {value}\n"
            if active is not None:
                lines[active] = new_line
                continue

            commented = next((i for i in range(start, end) if self._commented_key_line(key).match(lines[i])), None)
            if commented is not None:
                lines[commented] = new_line
                continue

            insert_at = end
            while insert_at > start and not lines[insert_at - 1].strip():
                insert_at -= 1
            lines.insert(insert_at, new_line)
            bounds = (start, end + 1)

        self._write_lines(lines)

    def replace_section(self, section: str, values: dict[str, str]) -> None:
        """Replace every active key of a section, keeping its comments."""
        lines = self._read_lines()
        bounds = self._section_bounds(lines, section)
        if bounds is None:
            if not values:
                return
            bounds = self._append_section(lines, section)

        start, end = bounds
        kept = [
            line for line in lines[start:end]
            if not line.strip() or line.strip().startswith(("#", ";"))
        ]
        while kept and not kept[-1].strip():
            kept.pop()
        new_lines = kept + [f"{key} = {value}\n" for key, value in values.items()]
        if end < len(lines):
            new_lines.append("\n")
        lines[start:end] = new_lines
        self._write_lines(lines)
