from auto_cpufreq.platform import cpu, sysfs
from tests.conftest import write


def test_intel_pstate_turbo_is_inverse_logic(fake_sysfs):
    cpu_root = fake_sysfs["cpu_root"]
    write(cpu_root / "intel_pstate" / "no_turbo", "0")  # 0 == turbo on

    assert cpu.get_turbo() is True
    assert cpu.set_turbo(False)
    assert (cpu_root / "intel_pstate" / "no_turbo").read_text().strip() == "1"
    assert cpu.get_turbo() is False


def test_acpi_cpufreq_boost_is_direct_logic(fake_sysfs):
    cpu_root = fake_sysfs["cpu_root"]
    write(cpu_root / "cpufreq" / "boost", "1")

    assert cpu.get_turbo() is True
    assert cpu.set_turbo(False)
    assert (cpu_root / "cpufreq" / "boost").read_text().strip() == "0"


def test_amd_pstate_active_not_directly_controllable(fake_sysfs):
    cpu_root = fake_sysfs["cpu_root"]
    write(cpu_root / "amd_pstate" / "status", "active")

    assert cpu.detect_turbo_control() is None
    assert cpu.get_turbo() is None
    assert cpu.set_turbo(True) is False
    assert cpu.amd_pstate_active() is True


def test_no_turbo_control_available(fake_sysfs):
    assert cpu.detect_turbo_control() is None
    assert cpu.get_turbo() is None
    assert cpu.is_amd_pstate() is False


def test_epp_must_be_performance_only_when_intel_pstate_active_and_gov_performance(fake_sysfs):
    cpu_root = fake_sysfs["cpu_root"]
    write(cpu_root / "intel_pstate" / "status", "active")

    assert cpu.epp_must_be_performance("performance") is True
    assert cpu.epp_must_be_performance("powersave") is False


def test_epp_must_be_performance_false_when_passive(fake_sysfs):
    cpu_root = fake_sysfs["cpu_root"]
    write(cpu_root / "intel_pstate" / "status", "passive")

    assert cpu.epp_must_be_performance("performance") is False


def test_epp_must_be_performance_amd_active(fake_sysfs):
    cpu_root = fake_sysfs["cpu_root"]
    write(cpu_root / "amd_pstate" / "status", "active")

    assert cpu.epp_must_be_performance("performance") is True
