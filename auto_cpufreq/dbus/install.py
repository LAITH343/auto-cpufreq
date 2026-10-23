import asyncio
import grp
import os
import pwd
import signal
import sys
from pathlib import Path
from subprocess import run

from dbus_fast import BusType, Message, MessageType
from dbus_fast.aio import MessageBus

from auto_cpufreq.dbus.service import BUS_NAME
from auto_cpufreq.globals import IS_INSTALLED_WITH_SNAP

GROUP = "auto-cpufreq"
POLICY_FILE = Path(f"/etc/dbus-1/system.d/{BUS_NAME}.conf")
ACTIVATION_FILE = Path(f"/usr/share/dbus-1/system-services/{BUS_NAME}.service")

POLICY = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-BUS Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <policy user="root">
    <allow own="{BUS_NAME}"/>
    <allow send_destination="{BUS_NAME}"/>
  </policy>
  <policy group="{GROUP}">
    <allow send_destination="{BUS_NAME}"/>
  </policy>
  <policy context="default">
    <deny own="{BUS_NAME}"/>
    <deny send_destination="{BUS_NAME}"/>
  </policy>
</busconfig>
"""

ACTIVATION = f"""[D-BUS Service]
Name={BUS_NAME}
Exec={sys.executable} -m auto_cpufreq.dbus
User=root
"""


def is_dbus_interface_installed() -> bool:
    return POLICY_FILE.exists() or ACTIVATION_FILE.exists()


def install_dbus_interface() -> bool:
    if IS_INSTALLED_WITH_SNAP:
        print("The D-Bus interface is not available for the snap package")
        return False

    print("* Creating group:", GROUP)
    if not _group_exists() and run(["groupadd", "--system", GROUP]).returncode != 0:
        print(f"ERROR: failed to create group {GROUP}")
        return False

    user = _invoking_user()
    if user is None:
        print(f"* No invoking user found, add users to the group with: usermod -aG {GROUP} <user>")
    else:
        print(f"* Adding {user} to group {GROUP}")
        if run(["usermod", "-aG", GROUP, user]).returncode != 0:
            print(f"ERROR: failed to add {user} to group {GROUP}")
            return False

    print("* Installing D-Bus policy:", POLICY_FILE)
    _write(POLICY_FILE, POLICY)
    print("* Installing D-Bus service:", ACTIVATION_FILE)
    _write(ACTIVATION_FILE, ACTIVATION)

    _reload_bus_config()
    print("\nD-Bus interface installed.")
    if user is not None:
        print(f"Log out and back in so {user} gets the {GROUP} group.")
    return True


def remove_dbus_interface() -> bool:
    if IS_INSTALLED_WITH_SNAP:
        print("The D-Bus interface is not available for the snap package")
        return False

    for path in (ACTIVATION_FILE, POLICY_FILE):
        if path.exists():
            print("* Removing", path)
            path.unlink()

    _reload_bus_config()
    _stop_running_service()

    if _group_exists():
        print("* Removing group:", GROUP)
        if run(["groupdel", GROUP]).returncode != 0:
            print(f"ERROR: failed to remove group {GROUP}")
            return False

    print("\nD-Bus interface removed.")
    return True


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    os.chmod(path, 0o644)


def _group_exists() -> bool:
    try:
        grp.getgrnam(GROUP)
        return True
    except KeyError:
        return False


def _invoking_user() -> str | None:
    user = os.environ.get("SUDO_USER")
    if user and user != "root":
        return user

    uid = os.environ.get("PKEXEC_UID")
    if uid and uid.isdigit() and int(uid) != 0:
        try:
            return pwd.getpwuid(int(uid)).pw_name
        except KeyError:
            return None
    return None


async def _call_bus(member: str, signature: str = "", body: list | None = None):
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    try:
        reply = await bus.call(
            Message(
                destination="org.freedesktop.DBus",
                path="/org/freedesktop/DBus",
                interface="org.freedesktop.DBus",
                member=member,
                signature=signature,
                body=body or [],
            )
        )
        return reply.body if reply.message_type == MessageType.METHOD_RETURN else None
    finally:
        bus.disconnect()


def _reload_bus_config() -> None:
    try:
        asyncio.run(_call_bus("ReloadConfig"))
    except Exception as e:
        print(f"WARNING: could not reload the D-Bus configuration ({e}), a reboot may be needed")


def _stop_running_service() -> None:
    try:
        body = asyncio.run(_call_bus("GetConnectionUnixProcessID", "s", [BUS_NAME]))
    except Exception:
        return
    if body:
        os.kill(body[0], signal.SIGTERM)
