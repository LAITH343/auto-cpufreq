from dataclasses import dataclass
from enum import Enum
from math import isclose

from auto_cpufreq.policy.profile import BATTERY, CHARGER

# system load (1-min average) thresholds, scaled by core count, at which turbo
# starts being considered for the "high system load" branch
PERFORMANCE_LOAD_THRESHOLD_PCT = 50
POWERSAVE_LOAD_THRESHOLD_PCT = 75

# per-branch average-core-temperature ceiling above which turbo is turned off,
# even though cpuload is below the cpuload trigger. Only the charger profile
# gates on temperature; battery profile never did (existing behavior).
CHARGER_HIGH_CPU_TEMP_LIMIT = 70
CHARGER_HIGH_SYSTEM_TEMP_LIMIT = 65

CPU_LOAD_TURBO_TRIGGER = 20  # cpuload (1s sample) at/above which turbo always turns on


class LoadStatus(str, Enum):
    HIGH_CPU = "High CPU load"
    HIGH_SYSTEM = "High system load"
    OPTIMAL = "Load optimal"


@dataclass
class TurboInputs:
    profile: str  # policy.profile.CHARGER | BATTERY
    cpu_count: int
    cpu_percent: float          # psutil.cpu_percent(percpu=False, interval=0.01)
    max_percpu_percent: float   # max(psutil.cpu_percent(percpu=True, interval=0.01))
    cpuload: float              # psutil.cpu_percent(interval=1)
    load1m: float                # os.getloadavg()[0]
    avg_temp: float


@dataclass
class TurboDecision:
    turbo_on: bool
    load_status: LoadStatus
    temp_limit: int | None       # temperature ceiling that applied, if any


def performance_load_threshold(cpu_count: int) -> float:
    return (PERFORMANCE_LOAD_THRESHOLD_PCT * cpu_count) / 100


def powersave_load_threshold(cpu_count: int) -> float:
    return (POWERSAVE_LOAD_THRESHOLD_PCT * cpu_count) / 100


def decide_turbo(inputs: TurboInputs) -> TurboDecision:
    if inputs.profile == CHARGER:
        threshold = performance_load_threshold(inputs.cpu_count)
        if inputs.cpu_percent >= 20.0 or inputs.max_percpu_percent >= 75:
            status = LoadStatus.HIGH_CPU
            temp_limit = CHARGER_HIGH_CPU_TEMP_LIMIT
        elif inputs.load1m >= threshold:
            status = LoadStatus.HIGH_SYSTEM
            temp_limit = CHARGER_HIGH_SYSTEM_TEMP_LIMIT
        else:
            status = LoadStatus.OPTIMAL
            temp_limit = None
    else:
        threshold = powersave_load_threshold(inputs.cpu_count)
        if inputs.cpu_percent >= 30.0 or isclose(inputs.max_percpu_percent, 100):
            status = LoadStatus.HIGH_CPU
        elif inputs.load1m > threshold:
            status = LoadStatus.HIGH_SYSTEM
        else:
            status = LoadStatus.OPTIMAL
        temp_limit = None  # battery profile never gates turbo on temperature

    if inputs.cpuload >= CPU_LOAD_TURBO_TRIGGER:
        turbo_on = True
    elif temp_limit is not None and inputs.avg_temp >= temp_limit:
        turbo_on = False
    elif temp_limit is not None:
        turbo_on = True
    else:
        turbo_on = False

    return TurboDecision(turbo_on=turbo_on, load_status=status, temp_limit=temp_limit)
