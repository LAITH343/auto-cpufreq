from __future__ import annotations

import os
from configparser import ConfigParser, Error as ConfigParserError
from dataclasses import dataclass, field, fields
from pathlib import Path

from dbus_fast import Variant

from auto_cpufreq.battery_scripts.battery import get_battery_device
from auto_cpufreq.battery_scripts.ideapad_laptop import IdeapadBatteryDevice
from auto_cpufreq.core import (
    CPU_SYSFS_ROOT,
    HWP_DYNAMIC_BOOST_PATH,
    daemon_is_running,
    get_formatted_version,
    get_override,
    get_turbo_override,
    intel_pstate_active,
)
from auto_cpufreq.globals import ALL_GOVERNORS, IS_INSTALLED_WITH_SNAP, POWER_SUPPLY_DIR
from auto_cpufreq.modules.platform_profile import platform_profile
from auto_cpufreq.modules.system_info import BatteryInfo, CoreInfo, SystemInfo, SystemReport
from auto_cpufreq.power_helper import bluetoothctl_exists

API_VERSION = 1

PROFILE_SECTIONS = ("charger", "battery")
IGNORE_LIST_SECTION = "power_supply_ignore_list"
BLUETOOTH_CONFIG = Path("/etc/bluetooth/main.conf")


class DbusModel:
    """Base for models sent over D-Bus as a{sv}; fields set to None are omitted."""

    SIGNATURES: dict[str, str] = {}

    def to_dbus(self) -> dict[str, Variant]:
        packed = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if value is None:
                continue
            signature = self.SIGNATURES[f.name]
            if isinstance(value, DbusModel):
                value = value.to_dbus()
            elif signature == "aa{sv}":
                value = [item.to_dbus() for item in value]
            packed[f.name] = Variant(signature, value)
        return packed


@dataclass
class CoreModel(DbusModel):
    SIGNATURES = {"id": "i", "usage": "d", "temperature": "d", "frequency_mhz": "d"}

    id: int
    usage: float
    temperature: float
    frequency_mhz: float

    @classmethod
    def from_core_info(cls, core: CoreInfo) -> "CoreModel":
        return cls(
            id=core.id,
            usage=float(core.usage),
            temperature=float(core.temperature),
            frequency_mhz=float(core.frequency),
        )


@dataclass
class BatteryModel(DbusModel):
    SIGNATURES = {
        "present": "b",
        "name": "s",
        "status": "s",
        "level": "i",
        "is_charging": "b",
        "is_ac_plugged": "b",
        "power_watts": "d",
        "start_threshold": "i",
        "stop_threshold": "i",
    }

    present: bool
    name: str | None = None
    status: str = "unknown"
    level: int | None = None
    is_charging: bool | None = None
    is_ac_plugged: bool | None = None
    power_watts: float | None = None
    start_threshold: int | None = None
    stop_threshold: int | None = None

    @classmethod
    def from_battery_info(cls, info: BatteryInfo, battery_path: str | None) -> "BatteryModel":
        return cls(
            present=battery_path is not None,
            name=os.path.basename(battery_path) if battery_path else None,
            status=_battery_status(battery_path),
            level=info.battery_level,
            is_charging=info.is_charging,
            is_ac_plugged=info.is_ac_plugged,
            power_watts=info.power_watts,
            start_threshold=info.charging_start_threshold,
            stop_threshold=info.charging_stop_threshold,
        )

    @classmethod
    def read(cls) -> "BatteryModel":
        return cls.from_battery_info(SystemInfo.battery_info(), SystemInfo.get_battery_path())


@dataclass
class ReportModel(DbusModel):
    SIGNATURES = {
        "distro_name": "s",
        "distro_version": "s",
        "arch": "s",
        "processor_model": "s",
        "kernel_version": "s",
        "cpu_driver": "s",
        "total_cores": "i",
        "governor": "s",
        "epp": "s",
        "epb": "s",
        "hwp_dynamic_boost": "b",
        "fan_rpm": "i",
        "cpu_usage": "d",
        "cpu_min_freq_mhz": "d",
        "cpu_max_freq_mhz": "d",
        "load": "d",
        "load_avg": "ad",
        "avg_temp": "d",
        "turbo_on": "b",
        "turbo_amd_auto": "b",
        "offline_cpus": "ai",
        "platform_profile": "s",
        "cores": "aa{sv}",
        "battery": "a{sv}",
    }

    distro_name: str
    distro_version: str
    arch: str
    processor_model: str
    kernel_version: str
    cpu_driver: str
    total_cores: int | None
    governor: str | None
    epp: str | None
    epb: str | None
    hwp_dynamic_boost: bool | None
    fan_rpm: int | None
    cpu_usage: float
    cpu_min_freq_mhz: float | None
    cpu_max_freq_mhz: float | None
    load: float
    load_avg: list[float] | None
    avg_temp: float | None
    turbo_on: bool | None
    turbo_amd_auto: bool | None
    offline_cpus: list[int]
    platform_profile: str | None
    cores: list[CoreModel]
    battery: BatteryModel

    @classmethod
    def from_system_report(cls, report: SystemReport, battery_path: str | None) -> "ReportModel":
        turbo_on, turbo_amd_auto = report.is_turbo_on
        return cls(
            distro_name=report.distro_name,
            distro_version=report.distro_ver,
            arch=report.arch,
            processor_model=report.processor_model,
            kernel_version=report.kernel_version,
            cpu_driver=report.cpu_driver,
            total_cores=report.total_core,
            governor=report.current_gov,
            epp=report.current_epp,
            epb=report.current_epb,
            hwp_dynamic_boost=report.current_hwp_dynamic_boost,
            fan_rpm=report.cpu_fan_speed,
            cpu_usage=float(report.cpu_usage),
            cpu_min_freq_mhz=report.cpu_min_freq,
            cpu_max_freq_mhz=report.cpu_max_freq,
            load=float(report.load),
            load_avg=[float(v) for v in report.avg_load] if report.avg_load else None,
            avg_temp=float(report.cpu_avg_temp) if report.cpu_avg_temp is not None else None,
            turbo_on=turbo_on,
            turbo_amd_auto=turbo_amd_auto,
            offline_cpus=list(report.offline_cpus),
            platform_profile=report.platform_profile.current,
            cores=[CoreModel.from_core_info(core) for core in report.cores_info],
            battery=BatteryModel.from_battery_info(report.battery_info, battery_path),
        )

    @classmethod
    def read(cls, system_info: SystemInfo) -> "ReportModel":
        return cls.from_system_report(system_info.generate_system_report(), SystemInfo.get_battery_path())


@dataclass
class OverridesModel(DbusModel):
    SIGNATURES = {"governor_override": "s", "turbo_override": "s", "active_governor": "s", "turbo_on": "b"}

    governor_override: str
    turbo_override: str
    active_governor: str | None
    turbo_on: bool | None

    @classmethod
    def read(cls) -> "OverridesModel":
        governor_override = get_override()
        return cls(
            governor_override="auto" if governor_override == "default" else governor_override,
            turbo_override=get_turbo_override(),
            active_governor=SystemInfo.current_gov(),
            turbo_on=SystemInfo.turbo_on()[0],
        )


@dataclass
class ConfigModel(DbusModel):
    SIGNATURES = {
        "path": "s",
        "exists": "b",
        "charger": "a{ss}",
        "battery": "a{ss}",
        "ignore_list": "as",
        "bluetooth_boot": "b",
        "error": "s",
    }

    path: str
    exists: bool
    charger: dict[str, str] = field(default_factory=dict)
    battery: dict[str, str] = field(default_factory=dict)
    ignore_list: list[str] = field(default_factory=list)
    bluetooth_boot: bool | None = None
    error: str | None = None

    @classmethod
    def read(cls, path: str) -> "ConfigModel":
        model = cls(path=path, exists=os.path.isfile(path), bluetooth_boot=read_bluetooth_boot())
        if not model.exists:
            return model

        parser = ConfigParser()
        try:
            parser.read(path)
        except ConfigParserError as e:
            model.error = str(e)
            return model

        for section in PROFILE_SECTIONS:
            if parser.has_section(section):
                setattr(model, section, dict(parser.items(section)))
        if parser.has_section(IGNORE_LIST_SECTION):
            model.ignore_list = [value for _, value in parser.items(IGNORE_LIST_SECTION)]
        return model


@dataclass
class PowerSupplyModel(DbusModel):
    SIGNATURES = {"name": "s", "type": "s"}

    name: str
    type: str


@dataclass
class CapabilitiesModel(DbusModel):
    SIGNATURES = {
        "governors": "as",
        "epp_choices": "as",
        "epb": "b",
        "hwp_dynamic_boost": "b",
        "platform_profiles": "as",
        "platform_profile_writable": "b",
        "hw_min_freq_khz": "i",
        "hw_max_freq_khz": "i",
        "turbo": "b",
        "power_supplies": "aa{sv}",
        "batteries": "as",
        "charge_control": "s",
        "bluetooth": "b",
    }

    governors: list[str]
    epp_choices: list[str]
    epb: bool
    hwp_dynamic_boost: bool
    platform_profiles: list[str]
    platform_profile_writable: bool
    hw_min_freq_khz: int | None
    hw_max_freq_khz: int | None
    turbo: bool
    power_supplies: list[PowerSupplyModel]
    batteries: list[str]
    charge_control: str
    bluetooth: bool

    @classmethod
    def read(cls) -> "CapabilitiesModel":
        epp_choices = _read_sysfs(CPU_SYSFS_ROOT / "cpu0/cpufreq/energy_performance_available_preferences")
        power_supplies = _power_supplies()
        profile = platform_profile.snapshot()
        turbo_on, turbo_amd_auto = SystemInfo.turbo_on()
        return cls(
            governors=_available_governors(),
            epp_choices=epp_choices.split() if epp_choices else [],
            epb=(CPU_SYSFS_ROOT / "cpu0/power/energy_perf_bias").exists(),
            hwp_dynamic_boost=HWP_DYNAMIC_BOOST_PATH.exists() and intel_pstate_active(),
            platform_profiles=list(profile.available_profiles),
            platform_profile_writable=profile.control_available,
            hw_min_freq_khz=_read_sysfs_int(CPU_SYSFS_ROOT / "cpu0/cpufreq/cpuinfo_min_freq"),
            hw_max_freq_khz=_read_sysfs_int(CPU_SYSFS_ROOT / "cpu0/cpufreq/cpuinfo_max_freq"),
            turbo=turbo_on is not None or turbo_amd_auto is not None,
            power_supplies=power_supplies,
            batteries=[supply.name for supply in power_supplies if supply.type.lower() == "battery"],
            charge_control=_charge_control(),
            bluetooth=bluetoothctl_exists and not IS_INSTALLED_WITH_SNAP,
        )


@dataclass
class BatteryConfigModel(DbusModel):
    SIGNATURES = {
        "battery_device": "s",
        "enable_thresholds": "b",
        "start_threshold": "i",
        "stop_threshold": "i",
        "conservation_mode": "b",
    }

    battery_device: str | None
    enable_thresholds: bool
    start_threshold: int | None
    stop_threshold: int | None
    conservation_mode: bool | None

    @classmethod
    def read(cls, config: ConfigModel) -> "BatteryConfigModel":
        battery = config.battery
        return cls(
            battery_device=battery.get("battery_device") or None,
            enable_thresholds=battery.get("enable_thresholds", "").strip().lower() == "true",
            start_threshold=_parse_int(battery.get("start_threshold")),
            stop_threshold=_parse_int(battery.get("stop_threshold")),
            conservation_mode=_parse_bool(battery.get("ideapad_laptop_conservation_mode")),
        )


@dataclass
class StatusModel(DbusModel):
    SIGNATURES = {"api_version": "i", "daemon_running": "b", "version": "s", "config_path": "s"}

    api_version: int
    daemon_running: bool
    version: str | None
    config_path: str

    @classmethod
    def read(cls, config_path: str) -> "StatusModel":
        try:
            version = get_formatted_version()
        except Exception:
            version = None
        if version is not None and version.startswith("Package "):
            version = None
        return cls(
            api_version=API_VERSION,
            daemon_running=bool(daemon_is_running()),
            version=version,
            config_path=config_path,
        )


def read_bluetooth_boot() -> bool | None:
    if not bluetoothctl_exists:
        return None
    try:
        lines = BLUETOOTH_CONFIG.read_text().splitlines()
    except OSError:
        return None

    in_policy_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("["):
            in_policy_section = stripped.lower() == "[policy]"
            continue
        if in_policy_section and stripped.startswith("AutoEnable="):
            return stripped.split("=", 1)[1].strip().lower() == "true"
    return True


def _charge_control() -> str:
    device = get_battery_device()
    if device is None:
        return "none"
    if isinstance(device, IdeapadBatteryDevice):
        return "conservation" if device.conservation_mode_path else "none"
    if device.start_paths and device.stop_paths:
        return "thresholds"
    return "none"


def _power_supplies() -> list[PowerSupplyModel]:
    try:
        names = sorted(os.listdir(POWER_SUPPLY_DIR))
    except OSError:
        return []
    return [
        PowerSupplyModel(name=name, type=_read_sysfs(Path(POWER_SUPPLY_DIR, name, "type")) or "Unknown")
        for name in names
    ]


def _battery_status(battery_path: str | None) -> str:
    status = _read_sysfs(Path(battery_path, "status")) if battery_path else None
    if not status:
        return "unknown"
    status = status.lower().replace(" ", "-")
    return status if status in ("charging", "discharging", "not-charging", "full") else "unknown"


def _available_governors() -> list[str]:
    """Governors in sysfs plus those whose module the kernel loads on first use."""
    loaded = (_read_sysfs(CPU_SYSFS_ROOT / "cpu0/cpufreq/scaling_available_governors") or "").split()
    modules = Path("/lib/modules", os.uname().release, "kernel/drivers/cpufreq")
    return [
        gov for gov in ALL_GOVERNORS
        if gov in loaded or any(modules.glob(f"cpufreq_{gov}.ko*"))
    ]


def _read_sysfs(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def _read_sysfs_int(path: Path) -> int | None:
    return _parse_int(_read_sysfs(path))


def _parse_int(value: str | None) -> int | None:
    value = (value or "").strip()
    return int(value) if value.isdigit() else None


def _parse_bool(value: str | None) -> bool | None:
    value = (value or "").strip().lower()
    if value == "true":
        return True
    if value == "false":
        return False
    return None
