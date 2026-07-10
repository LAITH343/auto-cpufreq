import pytest

from auto_cpufreq.policy.profile import BATTERY, CHARGER
from auto_cpufreq.policy.turbo import LoadStatus, TurboInputs, decide_turbo

CPU_COUNT = 4  # performance threshold -> 2.0, powersave threshold -> 3.0


def inputs(profile, cpu_percent=0, max_percpu_percent=0, cpuload=0, load1m=0, avg_temp=0):
    return TurboInputs(
        profile=profile,
        cpu_count=CPU_COUNT,
        cpu_percent=cpu_percent,
        max_percpu_percent=max_percpu_percent,
        cpuload=cpuload,
        load1m=load1m,
        avg_temp=avg_temp,
    )


# --- charger profile: high-cpu branch (temp ceiling 70) ---

def test_charger_high_cpu_load_trigger_wins_over_temp():
    d = decide_turbo(inputs(CHARGER, cpu_percent=25, cpuload=25, avg_temp=80))
    assert d.load_status == LoadStatus.HIGH_CPU
    assert d.turbo_on is True


def test_charger_high_cpu_hot_turns_turbo_off():
    d = decide_turbo(inputs(CHARGER, cpu_percent=25, cpuload=5, avg_temp=75))
    assert d.load_status == LoadStatus.HIGH_CPU
    assert d.turbo_on is False


def test_charger_high_cpu_cool_keeps_turbo_on():
    d = decide_turbo(inputs(CHARGER, cpu_percent=25, cpuload=5, avg_temp=50))
    assert d.load_status == LoadStatus.HIGH_CPU
    assert d.turbo_on is True


def test_charger_high_cpu_via_max_percpu():
    d = decide_turbo(inputs(CHARGER, max_percpu_percent=80, cpuload=25))
    assert d.load_status == LoadStatus.HIGH_CPU


# --- charger profile: high-system branch (temp ceiling 65) ---

def test_charger_high_system_load_trigger_wins_over_temp():
    d = decide_turbo(inputs(CHARGER, load1m=2.5, cpuload=25, avg_temp=90))
    assert d.load_status == LoadStatus.HIGH_SYSTEM
    assert d.turbo_on is True


def test_charger_high_system_hot_turns_turbo_off():
    d = decide_turbo(inputs(CHARGER, load1m=2.5, cpuload=5, avg_temp=70))
    assert d.load_status == LoadStatus.HIGH_SYSTEM
    assert d.turbo_on is False


def test_charger_high_system_cool_keeps_turbo_on():
    d = decide_turbo(inputs(CHARGER, load1m=2.5, cpuload=5, avg_temp=50))
    assert d.load_status == LoadStatus.HIGH_SYSTEM
    assert d.turbo_on is True


# --- charger profile: optimal branch (no temp ceiling) ---

def test_charger_optimal_cpuload_trigger():
    d = decide_turbo(inputs(CHARGER, load1m=1.0, cpuload=25, avg_temp=99))
    assert d.load_status == LoadStatus.OPTIMAL
    assert d.turbo_on is True


def test_charger_optimal_low_cpuload_ignores_temp():
    d = decide_turbo(inputs(CHARGER, load1m=1.0, cpuload=5, avg_temp=5))
    assert d.load_status == LoadStatus.OPTIMAL
    assert d.turbo_on is False


# --- battery profile: temperature never gates turbo ---

def test_battery_high_cpu_via_percent():
    d = decide_turbo(inputs(BATTERY, cpu_percent=35, cpuload=5, avg_temp=99))
    assert d.load_status == LoadStatus.HIGH_CPU
    assert d.turbo_on is False  # cpuload < 20, and battery ignores temp entirely


def test_battery_high_cpu_via_max_percpu_isclose_100():
    d = decide_turbo(inputs(BATTERY, max_percpu_percent=100.0, cpuload=25))
    assert d.load_status == LoadStatus.HIGH_CPU
    assert d.turbo_on is True


def test_battery_high_system_load():
    d = decide_turbo(inputs(BATTERY, load1m=3.5, cpuload=25, avg_temp=99))
    assert d.load_status == LoadStatus.HIGH_SYSTEM
    assert d.turbo_on is True


def test_battery_high_system_load_low_cpuload_ignores_temp():
    d = decide_turbo(inputs(BATTERY, load1m=3.5, cpuload=5, avg_temp=5))
    assert d.load_status == LoadStatus.HIGH_SYSTEM
    assert d.turbo_on is False


def test_battery_optimal():
    d = decide_turbo(inputs(BATTERY, load1m=1.0, cpuload=25, avg_temp=99))
    assert d.load_status == LoadStatus.OPTIMAL
    assert d.turbo_on is True


def test_battery_optimal_low_cpuload():
    d = decide_turbo(inputs(BATTERY, load1m=1.0, cpuload=5, avg_temp=5))
    assert d.load_status == LoadStatus.OPTIMAL
    assert d.turbo_on is False


@pytest.mark.parametrize("cpuload", [20, 21, 100])
def test_cpuload_trigger_boundary_is_inclusive(cpuload):
    d = decide_turbo(inputs(CHARGER, load1m=1.0, cpuload=cpuload))
    assert d.turbo_on is True


def test_cpuload_just_under_trigger_is_not_enough():
    d = decide_turbo(inputs(CHARGER, load1m=1.0, cpuload=19.9))
    assert d.turbo_on is False
