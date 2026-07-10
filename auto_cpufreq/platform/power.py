import os
from pathlib import Path

from auto_cpufreq.config.config import config
from auto_cpufreq.globals import POWER_SUPPLY_DIR

# power supplies always ignored, regardless of user config
HARD_CODED_IGNORE_LIST = ["hidpp_battery"]


def get_power_supply_ignore_list() -> list[str]:
    conf = config.get_config()

    ignore_list = []
    if conf.has_section("power_supply_ignore_list"):
        for key in conf["power_supply_ignore_list"]:
            ignore_list.append(conf["power_supply_ignore_list"][key])

    ignore_list.extend(HARD_CODED_IGNORE_LIST)
    return ignore_list


def charging() -> bool:
    """Is the device charging (AC online) or discharging (on battery)."""
    if os.path.exists(Path(POWER_SUPPLY_DIR)):
        power_supplies = sorted(os.listdir(Path(POWER_SUPPLY_DIR)))
    else:
        return True  # no sysfs entries, nothing to do.

    ignore_list = get_power_supply_ignore_list()

    if len(power_supplies) == 0:
        return True  # nothing found (e.g. desktop), assume on powercable

    for supply in power_supplies:
        if any(item in supply for item in ignore_list):
            continue

        type_path = Path(POWER_SUPPLY_DIR + supply + "/type")
        if not type_path.exists():
            continue
        with open(type_path) as f:
            supply_type = f.read()[:-1]

        if supply_type == "Mains":
            online_path = Path(POWER_SUPPLY_DIR + supply + "/online")
            if not online_path.exists():
                continue
            with open(online_path) as f:
                if int(f.read()[:-1]) == 1:
                    return True  # we are definitely charging
        elif supply_type == "Battery":
            status_path = Path(POWER_SUPPLY_DIR + supply + "/status")
            if not status_path.exists():
                continue
            with open(status_path) as f:
                if str(f.read()[:-1]) == "Discharging":
                    return False

    return True  # cannot determine discharging state, assume on powercable
