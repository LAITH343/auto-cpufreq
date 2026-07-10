import pytest

from auto_cpufreq.platform import sysfs
from auto_cpufreq.platform import power as power_module


@pytest.fixture
def fake_sysfs(tmp_path, monkeypatch):
    """Fake sysfs tree mirroring /sys/devices/system/cpu, /sys/firmware and
    /sys/class/power_supply, with platform/sysfs.py + platform/power.py
    repointed at it."""
    cpu_root = tmp_path / "sys" / "devices" / "system" / "cpu"
    firmware_root = tmp_path / "sys" / "firmware"
    power_supply_dir = tmp_path / "sys" / "class" / "power_supply"

    for core in range(4):
        (cpu_root / f"cpu{core}" / "cpufreq").mkdir(parents=True)
        (cpu_root / f"cpu{core}" / "power").mkdir(parents=True)

    monkeypatch.setattr(sysfs, "CPU_ROOT", cpu_root)
    monkeypatch.setattr(sysfs, "FIRMWARE_ROOT", firmware_root)
    monkeypatch.setattr(power_module, "POWER_SUPPLY_DIR", str(power_supply_dir) + "/")
    monkeypatch.setattr("os.cpu_count", lambda: 4)

    return {
        "cpu_root": cpu_root,
        "firmware_root": firmware_root,
        "power_supply_dir": power_supply_dir,
    }


def write(path, value):
    """Write a sysfs-style file: trailing newline, like the kernel does."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{value}\n")
