from auto_cpufreq.platform import power
from tests.conftest import write


def test_charging_true_when_no_power_supplies(fake_sysfs):
    assert power.charging() is True


def test_charging_true_when_ac_online(fake_sysfs):
    supply_dir = fake_sysfs["power_supply_dir"]
    write(supply_dir / "AC" / "type", "Mains")
    write(supply_dir / "AC" / "online", "1")
    assert power.charging() is True


def test_charging_false_when_battery_discharging(fake_sysfs):
    supply_dir = fake_sysfs["power_supply_dir"]
    write(supply_dir / "AC" / "type", "Mains")
    write(supply_dir / "AC" / "online", "0")
    write(supply_dir / "BAT0" / "type", "Battery")
    write(supply_dir / "BAT0" / "status", "Discharging")
    assert power.charging() is False


def test_charging_ignores_hidpp_battery(fake_sysfs):
    supply_dir = fake_sysfs["power_supply_dir"]
    write(supply_dir / "hidpp_battery_0" / "type", "Battery")
    write(supply_dir / "hidpp_battery_0" / "status", "Discharging")
    assert power.charging() is True
