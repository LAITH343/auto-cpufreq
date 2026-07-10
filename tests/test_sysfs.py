from auto_cpufreq.platform import sysfs
from tests.conftest import write


def test_get_set_governor(fake_sysfs):
    cpu_root = fake_sysfs["cpu_root"]
    for core in range(4):
        write(cpu_root / f"cpu{core}" / "cpufreq" / "scaling_governor", "powersave")

    assert sysfs.get_governor() == "powersave"
    assert sysfs.set_governor("performance")
    for core in range(4):
        assert (cpu_root / f"cpu{core}" / "cpufreq" / "scaling_governor").read_text() == "performance"


def test_available_governors(fake_sysfs):
    cpu_root = fake_sysfs["cpu_root"]
    write(cpu_root / "cpu0" / "cpufreq" / "scaling_available_governors", "performance powersave\n")
    assert sysfs.available_governors() == ["performance", "powersave"]


def test_epp_not_supported_when_file_missing(fake_sysfs):
    assert sysfs.epp_supported() is False
    assert sysfs.get_epp() is None


def test_epp_supported_and_set(fake_sysfs):
    cpu_root = fake_sysfs["cpu_root"]
    for core in range(4):
        write(cpu_root / f"cpu{core}" / "cpufreq" / "energy_performance_preference", "balance_performance")

    assert sysfs.epp_supported() is True
    assert sysfs.get_epp() == "balance_performance"
    sysfs.set_epp("performance")
    for core in range(4):
        assert (cpu_root / f"cpu{core}" / "cpufreq" / "energy_performance_preference").read_text() == "performance"


def test_epb_named_value_mapping(fake_sysfs):
    cpu_root = fake_sysfs["cpu_root"]
    for core in range(4):
        write(cpu_root / f"cpu{core}" / "power" / "energy_perf_bias", "6")

    assert sysfs.set_epb("balance_power")
    for core in range(4):
        assert (cpu_root / f"cpu{core}" / "power" / "energy_perf_bias").read_text() == "8"


def test_epb_raw_numeric_value(fake_sysfs):
    cpu_root = fake_sysfs["cpu_root"]
    write(cpu_root / "cpu0" / "power" / "energy_perf_bias", "6")
    assert sysfs.set_epb("3")
    assert (cpu_root / "cpu0" / "power" / "energy_perf_bias").read_text() == "3"


def test_epb_invalid_value_rejected(fake_sysfs):
    cpu_root = fake_sysfs["cpu_root"]
    write(cpu_root / "cpu0" / "power" / "energy_perf_bias", "6")
    assert sysfs.set_epb("nonsense") is False
    assert sysfs.set_epb("42") is False  # out of 0-15 range


def test_platform_profile_roundtrip(fake_sysfs):
    firmware_root = fake_sysfs["firmware_root"]
    write(firmware_root / "acpi" / "platform_profile", "balanced")
    assert sysfs.platform_profile_supported() is True
    assert sysfs.get_platform_profile() == "balanced"
    assert sysfs.set_platform_profile("performance")
    assert sysfs.get_platform_profile() == "performance"


def test_platform_profile_unsupported(fake_sysfs):
    assert sysfs.platform_profile_supported() is False


def test_platform_profile_skips_redundant_write(fake_sysfs):
    firmware_root = fake_sysfs["firmware_root"]
    pp_file = firmware_root / "acpi" / "platform_profile"
    write(pp_file, "balanced")
    before = pp_file.stat().st_mtime_ns
    pp_file.chmod(0o444)  # a write would fail, proving no write is attempted

    assert sysfs.set_platform_profile("balanced") is True
    assert pp_file.stat().st_mtime_ns == before


def test_frequency_limits(fake_sysfs):
    cpu_root = fake_sysfs["cpu_root"]
    write(cpu_root / "cpu0" / "cpufreq" / "cpuinfo_min_freq", 800000)
    write(cpu_root / "cpu0" / "cpufreq" / "cpuinfo_max_freq", 4000000)
    write(cpu_root / "cpu0" / "cpufreq" / "scaling_min_freq", 800000)
    write(cpu_root / "cpu0" / "cpufreq" / "scaling_max_freq", 3500000)

    assert sysfs.get_frequency_min_limit() == 800000
    assert sysfs.get_frequency_max_limit() == 4000000
    assert sysfs.get_frequency_min() == 800000
    assert sysfs.get_frequency_max() == 3500000

    assert sysfs.set_frequency_max(3000000)
    assert sysfs.get_frequency_max() == 3000000
