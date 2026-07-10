CHARGER = "charger"
BATTERY = "battery"


def decide_profile(override: str, is_charging: bool) -> str:
    """override: 'default' | 'powersave' | 'performance'. is_charging: from platform.power.charging()."""
    if override == "powersave":
        return BATTERY
    if override == "performance":
        return CHARGER
    return CHARGER if is_charging else BATTERY
