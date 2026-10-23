import asyncio
import sys
import time

from dbus_fast import BusType, RequestNameReply
from dbus_fast.aio import MessageBus
from dbus_fast.errors import DBusError
from dbus_fast.service import ServiceInterface, method

from auto_cpufreq.config.config import config, find_config_file
from auto_cpufreq.dbus import actions
from auto_cpufreq.dbus.models import (
    BatteryConfigModel,
    BatteryModel,
    CapabilitiesModel,
    ConfigModel,
    OverridesModel,
    ReportModel,
    StatusModel,
)
from auto_cpufreq.modules.system_info import system_info

BUS_NAME = "org.autocpufreq.Daemon"
OBJECT_PATH = "/org/autocpufreq/Daemon"
INTERFACE_NAME = "org.autocpufreq.Daemon"

ERROR_INVALID_ARGUMENT = "org.autocpufreq.Error.InvalidArgument"
ERROR_FAILED = "org.autocpufreq.Error.Failed"
ERROR_NOT_SUPPORTED = "org.autocpufreq.Error.NotSupported"

# The bus starts the service again on the next call, so it can exit when unused.
IDLE_TIMEOUT = 300


class DaemonInterface(ServiceInterface):
    def __init__(self, config_path: str) -> None:
        super().__init__(INTERFACE_NAME)
        self.config_path = config_path
        self.last_activity = time.monotonic()

    def _touch(self) -> None:
        self.last_activity = time.monotonic()

    async def _read(self, read):
        self._touch()
        model = await asyncio.get_running_loop().run_in_executor(None, read)
        return model.to_dbus()

    def _run(self, action, *args) -> None:
        self._touch()
        try:
            action(*args)
        except actions.InvalidArgument as e:
            raise DBusError(ERROR_INVALID_ARGUMENT, str(e))
        except actions.NotSupported as e:
            raise DBusError(ERROR_NOT_SUPPORTED, str(e))
        except actions.ActionError as e:
            raise DBusError(ERROR_FAILED, str(e))
        except OSError as e:
            raise DBusError(ERROR_FAILED, str(e))

    @method(name="GetStatus")
    async def get_status(self) -> "a{sv}":
        return await self._read(lambda: StatusModel.read(self.config_path))

    @method(name="GetReport")
    async def get_report(self) -> "a{sv}":
        return await self._read(lambda: ReportModel.read(system_info))

    @method(name="GetBattery")
    async def get_battery(self) -> "a{sv}":
        return await self._read(BatteryModel.read)

    @method(name="GetOverrides")
    async def get_overrides(self) -> "a{sv}":
        return await self._read(OverridesModel.read)

    @method(name="GetConfig")
    async def get_config(self) -> "a{sv}":
        return await self._read(lambda: ConfigModel.read(self.config_path))

    @method(name="GetBatteryConfig")
    async def get_battery_config(self) -> "a{sv}":
        return await self._read(lambda: BatteryConfigModel.read(ConfigModel.read(self.config_path)))

    @method(name="GetCapabilities")
    async def get_capabilities(self) -> "a{sv}":
        return await self._read(CapabilitiesModel.read)

    @method(name="SetGovernorOverride")
    def set_governor_override(self, value: "s"):
        self._run(actions.set_governor_override, value)

    @method(name="SetTurboOverride")
    def set_turbo_override(self, value: "s"):
        self._run(actions.set_turbo_override_mode, value)

    @method(name="ResetOverrides")
    def reset_overrides(self):
        self._run(actions.reset_overrides)

    @method(name="SetConfigSection")
    def set_config_section(self, section: "s", values: "a{ss}"):
        self._run(actions.set_config_section, self.config_path, section, values)

    @method(name="SetIgnoreList")
    def set_ignore_list(self, names: "as"):
        self._run(actions.set_ignore_list, self.config_path, names)

    @method(name="SetBatteryConfig")
    def set_battery_config(self, values: "a{ss}"):
        self._run(actions.set_battery_config, self.config_path, values)

    @method(name="SetBluetoothBoot")
    def set_bluetooth_boot(self, enabled: "b"):
        self._run(actions.set_bluetooth_boot, enabled)


async def serve(bus_type: BusType, config_file=None) -> int:
    config_path = find_config_file(config_file)
    config.set_path(config_path)
    config.notifier.start()

    bus = await MessageBus(bus_type=bus_type).connect()
    try:
        interface = DaemonInterface(config_path)
        bus.export(OBJECT_PATH, interface)

        reply = await bus.request_name(BUS_NAME)
        if reply != RequestNameReply.PRIMARY_OWNER:
            print(f"{BUS_NAME} is already owned by another process")
            return 1

        while bus.connected:
            await asyncio.sleep(10)
            if time.monotonic() - interface.last_activity > IDLE_TIMEOUT:
                break
        return 0
    finally:
        bus.disconnect()
        config.notifier.stop()


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    bus_type = BusType.SESSION if "--session" in argv else BusType.SYSTEM
    config_file = argv[argv.index("--config") + 1] if "--config" in argv[:-1] else None
    return asyncio.run(serve(bus_type, config_file))
