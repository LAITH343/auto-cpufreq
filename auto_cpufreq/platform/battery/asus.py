#!/usr/bin/env python3

from auto_cpufreq.platform.battery.shared import BatteryDevice


class AsusBatteryDevice(BatteryDevice):
    def __init__(self):
        super().__init__()
