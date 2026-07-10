#!/usr/bin/env python3
#
# auto-cpufreq - core functionality
import click, distro, os, platform, psutil, sys
from importlib.metadata import metadata, PackageNotFoundError
from math import isclose
from pathlib import Path
from pickle import dump, load
from re import search
from requests import get, exceptions
from shutil import copy
from subprocess import call, check_output, DEVNULL, getoutput, run
from time import sleep
from warnings import filterwarnings

from auto_cpufreq.config.config import config
from auto_cpufreq.globals import (
    ALL_GOVERNORS, AVAILABLE_GOVERNORS, AVAILABLE_GOVERNORS_SORTED, GITHUB, IS_INSTALLED_WITH_AUR, IS_INSTALLED_WITH_SNAP, SNAP_DAEMON_CHECK
)
from auto_cpufreq.power_helper import *
from auto_cpufreq.modules.system_info import SystemInfo
from auto_cpufreq.platform import cpu as platform_cpu
from auto_cpufreq.platform import sysfs as platform_sysfs
from auto_cpufreq.platform.power import charging, get_power_supply_ignore_list
from auto_cpufreq.policy.profile import CHARGER, BATTERY, decide_profile
from auto_cpufreq.policy.turbo import TurboInputs, TurboDecision, LoadStatus, decide_turbo
from auto_cpufreq.policy.settings import (
    PlatformFacts, decide_epp, decide_epb, decide_governor,
    PlatformProfileState, decide_platform_profile,
    FrequencyConfigError, decide_frequencies,
)

filterwarnings("ignore")

# add path to auto-cpufreq executables for GUI
if "PATH" in os.environ:
    os.environ["PATH"] += os.pathsep + "/usr/local/bin"
else:
    os.environ["PATH"] = "/usr/local/bin"

# ToDo:
# - replace get system/CPU load from: psutil.getloadavg() | available in 5.6.2)

SCRIPTS_DIR = Path("/usr/local/share/auto-cpufreq/scripts/")
CPUS = os.cpu_count()



# Note:
# "load1m" & "cpuload" can't be global vars and to in order to show correct data must be
# decraled where their execution takes place

# auto-cpufreq stats file path
auto_cpufreq_stats_file = None
auto_cpufreq_stats_path = None

# track governor override and turbo boost override
if IS_INSTALLED_WITH_SNAP:
    auto_cpufreq_stats_path = Path("/var/snap/auto-cpufreq/current/auto-cpufreq.stats")
    governor_override_state = Path("/var/snap/auto-cpufreq/current/override.pickle")
    turbo_override_state    = Path("/var/snap/auto-cpufreq/current/turbo-override.pickle")
else:
    auto_cpufreq_stats_path = Path("/var/run/auto-cpufreq.stats")
    governor_override_state = Path("/opt/auto-cpufreq/override.pickle")
    turbo_override_state    = Path("/opt/auto-cpufreq/turbo-override.pickle")

last_applied_config_section = None

def file_stats():
    global auto_cpufreq_stats_file
    auto_cpufreq_stats_file = open(auto_cpufreq_stats_path, "w")
    sys.stdout = auto_cpufreq_stats_file

def get_override():
    if os.path.isfile(governor_override_state):
        with open(governor_override_state, "rb") as store: return load(store)
    else: return "default"

def set_override(override):
    if override in ["powersave", "performance"]:
        with open(governor_override_state, "wb") as store:
            dump(override, store)
        print(f"Set governor override to {override}")
    elif override == "reset":
        if os.path.isfile(governor_override_state):
            os.remove(governor_override_state)
        print("Governor override removed")
    elif override is not None: print("Invalid option.\nUse force=performance, force=powersave, or force=reset")

def get_turbo_override():
    if os.path.isfile(turbo_override_state):
        with open(turbo_override_state, "rb") as store: return load(store)
    else: return "auto"

def set_turbo_override(override):
    if override in ["never", "always"]:
        with open(turbo_override_state, "wb") as store:
            dump(override, store)
        print(f"Set turbo boost override to {override}")
    elif override == "auto":
        if os.path.isfile(turbo_override_state):
            os.remove(turbo_override_state)
        print("Turbo override removed")
    elif override is not None: print("Invalid option.\nUse turbo=always, turbo=never, or turbo=auto")

# get distro name
try: dist_name = distro.id()
except PermissionError:
    # Current work-around for Pop!_OS where symlink causes permission issues
    print("[!] Warning: Cannot get distro name")
    if IS_INSTALLED_WITH_SNAP and os.path.exists("/etc/pop-os/os-release"):
        print("[!] Snap install on PopOS detected, you must manually run the following"
                " commands in another terminal:\n")
        print("[!] Backup the /etc/os-release file:")
        print("sudo mv /etc/os-release /etc/os-release-backup\n")
        print("[!] Create hardlink to /etc/os-release:")
        print("sudo ln /etc/pop-os/os-release /etc/os-release\n")
        print("[!] Aborting. Restart auto-cpufreq when you created the hardlink")
    else:
        print("[!] Check /etc/os-release permissions and make sure it is not a symbolic link")
        print("[!] Aborting...")
    sys.exit(1)

# display running version of auto-cpufreq
def app_version():
    print("auto-cpufreq version: ", end="")

    if IS_INSTALLED_WITH_SNAP: print(getoutput(r"echo \(Snap\) $SNAP_VERSION"))
    elif IS_INSTALLED_WITH_AUR: print(getoutput("pacman -Qi auto-cpufreq | grep Version"))
    else:
        try: print(get_formatted_version())
        except Exception as e: print(repr(e))

def check_for_update():
    # returns True if a new release is available from the GitHub repo

    # Specify the repository and package name
    # IT IS IMPORTANT TO  THAT IF THE REPOSITORY STRUCTURE IS CHANGED, THE FOLLOWING FUNCTION NEEDS TO BE UPDATED ACCORDINGLY
    # Fetch the latest release information from GitHub API
    latest_release_url = GITHUB.replace("github.com", "api.github.com/repos") + "/releases/latest"
    try:
        response = get(latest_release_url)
        if response.status_code == 200: latest_release = response.json()
        else:
            message = response.json().get("message")
            print("Error fetching recent release!")
            if message is not None and message.startswith("API rate limit exceeded"):
                print("GitHub Rate limit exceeded. Please try again later within 1 hour or use different network/VPN.")
            else: print("Unexpected status code:", response.status_code)
            return False
    except (exceptions.ConnectionError, exceptions.Timeout,
            exceptions.RequestException, exceptions.HTTPError):
        print("Error Connecting to server!")
        return False

    latest_version = latest_release.get("tag_name")

    if latest_version is not None:
        # Get the current version of auto-cpufreq
        # Extract version number from the output string
        output = check_output(['auto-cpufreq', '--version']).decode('utf-8')
        try: version_line = next((search(r'\d+\.\d+\.\d+', line).group() for line in output.split('\n') if line.startswith('auto-cpufreq version')), None)
        except AttributeError:
            print("Error Retrieving Current Version!")
            exit(1)
        installed_version = "v" + version_line
        #Check whether the same is installed or not
        # Compare the latest version with the installed version and perform update if necessary
        if latest_version == installed_version:
            print("auto-cpufreq is up to date")
            return False
        else:
            print(f"Updates are available,\nCurrent version: {installed_version}\nLatest version: {latest_version}")
            print("Note that your previous custom settings might be erased with the following update")
            return True
    # Handle the case where "tag_name" key doesn't exist
    else: print("Malformed Released data!\nReinstall manually or Open an issue on GitHub for help!")

def new_update(custom_dir):
    os.chdir(custom_dir)
    print(f"Cloning the latest release to {custom_dir}")
    run(["git", "clone", GITHUB+".git"])
    os.chdir("auto-cpufreq")
    print(f"package cloned to directory {custom_dir}")
    run(['./auto-cpufreq-installer'], input='i\n', encoding='utf-8')

def get_literal_version(package_name):
    try:
        package_metadata = metadata(package_name)
        package_name = package_metadata['Name']
        numbered_version, _, git_version = package_metadata['Version'].partition("+")

        return f"{numbered_version}+{git_version}" # Construct the literal version string

    except PackageNotFoundError: return f"Package '{package_name}' not found"

# return formatted version for a better readability
def get_formatted_version():
    splitted_version = get_literal_version("auto-cpufreq").split("+")
    return splitted_version[0] + ("" if len(splitted_version) > 1 else " (git: " + splitted_version[1] + ")")

def app_res_use():
    p = psutil.Process()
    print("auto-cpufreq system resource consumption:")
    print("cpu usage:", p.cpu_percent(), "%")
    print("memory use:", round(p.memory_percent(), 2), "%")

# set/change state of turbo
def turbo(value: bool = None):
    """
    Get and set turbo mode
    """
    control = platform_cpu.detect_turbo_control()
    if control is None:
        if platform_cpu.is_amd_pstate():
            if platform_cpu.amd_pstate_active():
                print("CPU turbo is controlled by amd-pstate-epp driver")
            # Basically, no other value should exist.
            return False
        print("Warning: CPU turbo is not available")
        return False

    turbo_override = get_turbo_override()
    if turbo_override != "auto":
        # Set the value in respect to if turbo override is enabled or not.
        if turbo_override == "always":
            value = True
        elif turbo_override == "never":
            value = False

    if value is not None:
        if not platform_cpu.set_turbo(value):
            print("Warning: Changing CPU turbo is not supported. Skipping.")
            return False

    return bool(platform_cpu.get_turbo())

def get_turbo(): print("Currently turbo boost is:", "on" if turbo() else "off")
def set_turbo(value:bool):
    print("Setting turbo boost:", "on" if value else "off")
    turbo(value)

def get_current_gov():
    return print("Currently using:", platform_sysfs.get_governor(), "governor")

def cpufreqctl():
    """
    deploy cpufreqctl.auto-cpufreq script
    """
    if not (IS_INSTALLED_WITH_SNAP or os.path.isfile("/usr/local/bin/cpufreqctl.auto-cpufreq")):
        copy(SCRIPTS_DIR / "cpufreqctl.sh", "/usr/local/bin/cpufreqctl.auto-cpufreq")
        call(["chmod", "a+x", "/usr/local/bin/cpufreqctl.auto-cpufreq"])

def cpufreqctl_restore():
    """
    remove cpufreqctl.auto-cpufreq script
    """
    if not IS_INSTALLED_WITH_SNAP and os.path.isfile("/usr/local/bin/cpufreqctl.auto-cpufreq"):
        os.remove("/usr/local/bin/cpufreqctl.auto-cpufreq")

def footer(l=79): print("\n" + "-" * l + "\n")

def deploy_complete_msg():
    print("\n" + "-" * 17 + " auto-cpufreq daemon installed and running " + "-" * 17 + "\n")
    print("To view live stats, run:\nauto-cpufreq --stats")
    print("\nauto-cpufreq makes all decisions automatically, if you would like to")
    print("configure certain setting to your own liking, please refer to:\nhttps://github.com/AdnanHodzic/auto-cpufreq#configuring-auto-cpufreq")
    print("\nTo disable and remove auto-cpufreq daemon, run:\nsudo auto-cpufreq --remove")
    footer()

def remove_complete_msg():
    print("\n" + "-" * 25 + " auto-cpufreq daemon removed " + "-" * 25 + "\n")
    print("auto-cpufreq successfully removed.")
    footer()

def deploy_daemon():
    print("\n" + "-" * 21 + " Deploying auto-cpufreq as a daemon " + "-" * 22 + "\n")

    cpufreqctl() # deploy cpufreqctl script func call

    bluetooth_disable() # turn off bluetooth on boot

    auto_cpufreq_stats_path.touch(exist_ok=True)

    print("\n* Deploy auto-cpufreq install script")
    copy(SCRIPTS_DIR / "auto-cpufreq-install.sh", "/usr/local/bin/auto-cpufreq-install")
    call(["chmod", "a+x", "/usr/local/bin/auto-cpufreq-install"])

    print("\n* Deploy auto-cpufreq remove script")
    copy(SCRIPTS_DIR / "auto-cpufreq-remove.sh", "/usr/local/bin/auto-cpufreq-remove")
    call(["chmod", "a+x", "/usr/local/bin/auto-cpufreq-remove"])

    # output warning if gnome power profile is running
    gnome_power_detect_install()
    gnome_power_svc_disable()

    tuned_svc_disable()

    tlp_service_detect() # output warning if TLP service is detected

    call("/usr/local/bin/auto-cpufreq-install", shell=True)

def remove_daemon():
    # check if auto-cpufreq is installed
    if not os.path.exists("/usr/local/bin/auto-cpufreq-remove"):
        print("\nauto-cpufreq daemon is not installed.\n")
        sys.exit(1)

    print("\n" + "-" * 21 + " Removing auto-cpufreq daemon " + "-" * 22 + "\n")

    bluetooth_enable() # turn on bluetooth on boot

    # output warning if gnome power profile is stopped
    gnome_power_rm_reminder()
    gnome_power_svc_enable()

    tuned_svc_enable()

    # run auto-cpufreq daemon remove script
    call("/usr/local/bin/auto-cpufreq-remove", shell=True)

    # remove auto-cpufreq-remove
    os.remove("/usr/local/bin/auto-cpufreq-remove")

    # delete override pickle if it exists
    if os.path.exists(governor_override_state):  os.remove(governor_override_state)

    # delete stats file
    if auto_cpufreq_stats_path.exists():
        if auto_cpufreq_stats_file is not None: auto_cpufreq_stats_file.close()
        auto_cpufreq_stats_path.unlink()

    cpufreqctl_restore() # restore original cpufrectl script

def gov_check():
    for gov in AVAILABLE_GOVERNORS:
        if gov not in ALL_GOVERNORS:
            print("\n" + "-" * 18 + " Checking for necessary scaling governors " + "-" * 19 + "\n")
            sys.exit("ERROR:\n\nCouldn't find any of the necessary scaling governors.\n")

def root_check():
    if not os.geteuid() == 0:
        print("\n" + "-" * 33 + " Root check " + "-" * 34 + "\n")
        print("ERROR:\n\nMust be run root for this functionality to work, i.e: \nsudo " + app_name)
        footer()
        exit(1)

def countdown(s):
    # Fix for wrong stats output and "TERM environment variable not set"
    os.environ["TERM"] = "xterm"

    print("\t\t\"auto-cpufreq\" is about to refresh ", end = "")

    # empty log file if size is larger then 10mb
    if auto_cpufreq_stats_file is not None:
        log_size = os.path.getsize(auto_cpufreq_stats_path)
        if log_size >= 1e+7:
            auto_cpufreq_stats_file.seek(0)
            auto_cpufreq_stats_file.truncate(0)

    # auto-refresh counter
    for remaining in range(s, -1, -1):
        if remaining <= 3 and remaining >= 0: print(".", end="", flush=True)
        sleep(s/3)

    print("\n\t\tExecuted on:", getoutput('date'))

# get cpu usage + system load for (last minute)
def get_load():    
    cpuload = psutil.cpu_percent(interval=1) # get CPU utilization as a percentage
    load1m, _, _ = os.getloadavg() # get system/CPU load

    print("\nTotal CPU usage:", cpuload, "%")
    print("Total system load: {:.2f}".format(load1m))
    from auto_cpufreq.modules.system_info import SystemInfo

    print("Average temp. of all cores: {:.2f} °C \n".format(SystemInfo.avg_temp()))

    return cpuload, load1m

def display_system_load_avg(): print(" (load average: {:.2f}, {:.2f}, {:.2f})".format(*os.getloadavg()))

def _conf_option(conf, section, option):
    return conf[section][option] if conf.has_option(section, option) else None


def gather_platform_facts() -> PlatformFacts:
    """Read the sysfs facts the policy/settings.py decisions need."""
    intel_present = platform_cpu.is_intel_pstate()
    amd_present = platform_cpu.is_amd_pstate()
    if intel_present:
        active_status = platform_sysfs.intel_pstate_status()
    elif amd_present:
        active_status = platform_sysfs.get_amd_pstate_status()
    else:
        active_status = None

    return PlatformFacts(
        epp_supported=platform_sysfs.epp_supported(),
        intel_pstate_present=intel_present,
        amd_pstate_present=amd_present,
        dynboost_enabled=platform_sysfs.hwp_dynamic_boost_enabled(),
        active_pstate_status=active_status,
    )


# module state carried across ticks (mirrors engine state in future phases)
_last_applied_platform_profile: dict = {}


def apply_platform_profile(conf, profile):
    global _last_applied_platform_profile

    state = PlatformProfileState(
        last_applied=_last_applied_platform_profile,
        last_applied_section=last_applied_config_section,
    )
    decision = decide_platform_profile(conf, profile, platform_sysfs.platform_profile_supported(), state)
    for message in decision.messages:
        print(message)

    if not decision.should_set:
        return

    if platform_sysfs.set_platform_profile(decision.value):
        _last_applied_platform_profile = {**_last_applied_platform_profile, profile: decision.value}
    else:
        print(f"Failed to set platform profile to {decision.value}")


def apply_energy_perf_bias(conf, profile, intel_pstate_present):
    configured_epb = _conf_option(conf, profile, "energy_perf_bias")
    epb, message = decide_epb(profile, configured_epb, intel_pstate_present)
    print(message)
    if epb is not None:
        platform_sysfs.set_epb(epb)


def apply_energy_perf_preference(conf, profile, gov, facts):
    configured_epp = _conf_option(conf, profile, "energy_performance_preference")
    decision = decide_epp(profile, gov, configured_epp, facts)
    for message in decision.messages:
        print(message)
    if decision.epp is not None:
        platform_sysfs.set_epp(decision.epp)


def build_turbo_inputs(profile, cpuload, load1m) -> TurboInputs:
    return TurboInputs(
        profile=profile,
        cpu_count=CPUS,
        cpu_percent=psutil.cpu_percent(percpu=False, interval=0.01),
        max_percpu_percent=max(psutil.cpu_percent(percpu=True, interval=0.01)),
        cpuload=cpuload,
        load1m=load1m,
        avg_temp=SystemInfo.avg_temp(),
    )


def _report_turbo_decision(inputs: TurboInputs, decision: TurboDecision):
    print(decision.load_status.value, end="")
    display_system_load_avg()
    if not decision.turbo_on:
        print(f"Optimal total CPU usage: {inputs.cpuload}%, high average core temp: {inputs.avg_temp}°C")


def apply_turbo(profile, cpuload, load1m):
    inputs = build_turbo_inputs(profile, cpuload, load1m)
    decision = decide_turbo(inputs)
    _report_turbo_decision(inputs, decision)
    set_turbo(decision.turbo_on)


def apply_turbo_override_or(profile, conf, cpuload, load1m):
    auto = _conf_option(conf, profile, "turbo") or "auto"
    auto = get_turbo_override() if (get_turbo_override() != "auto") else auto  # Override turbo if override file is present, otherwise stick to config.

    if auto == "always":
        print("Configuration file enforces turbo boost")
        set_turbo(True)
    elif auto == "never":
        print("Configuration file disables turbo boost")
        set_turbo(False)
    else:
        apply_turbo(profile, cpuload, load1m)


# set minimum and maximum CPU frequencies
def set_frequencies(power_supply):
    """
    Sets frequencies:
     - if option is used in auto-cpufreq.conf: use configured value
     - if option is disabled/no conf file used: set default frequencies
    Frequency setting is validated on each run and only applied when needed
    Caller passes the active profile ("battery" or "charger").
    """
    max_limit = platform_sysfs.get_frequency_max_limit()
    min_limit = platform_sysfs.get_frequency_min_limit()
    set_frequencies.max_limit = max_limit
    set_frequencies.min_limit = min_limit

    conf = config.get_config()

    try:
        decision = decide_frequencies(conf, power_supply, min_limit, max_limit)
    except FrequencyConfigError as e:
        print(str(e))
        exit(1)

    if platform_sysfs.get_frequency_max() != decision.max_value:
        print(f'Setting maximum CPU frequency to {round(decision.max_value/1000)} Mhz')
        platform_sysfs.set_frequency_max(decision.max_value)

    if platform_sysfs.get_frequency_min() != decision.min_value:
        print(f'Setting minimum CPU frequency to {round(decision.min_value/1000)} Mhz')
        platform_sysfs.set_frequency_min(decision.min_value)


def set_powersave():
    conf = config.get_config()
    gov = decide_governor(BATTERY, _conf_option(conf, "battery", "governor"), AVAILABLE_GOVERNORS_SORTED)
    print(f'Setting to use: "{gov}" governor')
    if get_override() != "default": print("Warning: governor overwritten using `--force` flag.")
    platform_sysfs.set_governor(gov)

    facts = gather_platform_facts()
    apply_energy_perf_preference(conf, "battery", gov, facts)
    apply_energy_perf_bias(conf, "battery", facts.intel_pstate_present)
    apply_platform_profile(conf, "battery")
    global last_applied_config_section
    last_applied_config_section = "battery"

    cpuload, load1m = get_load()
    apply_turbo_override_or("battery", conf, cpuload, load1m)

    set_frequencies("battery")
    footer()

def set_performance():
    conf = config.get_config()
    gov = decide_governor(CHARGER, _conf_option(conf, "charger", "governor"), AVAILABLE_GOVERNORS_SORTED)

    print(f'Setting to use: "{gov}" governor')
    if get_override() != "default": print("Warning: governor overwritten using `--force` flag.")
    platform_sysfs.set_governor(gov)

    facts = gather_platform_facts()
    apply_energy_perf_preference(conf, "charger", gov, facts)
    apply_energy_perf_bias(conf, "charger", facts.intel_pstate_present)
    apply_platform_profile(conf, "charger")
    global last_applied_config_section
    last_applied_config_section = "charger"

    cpuload, load1m = get_load()
    apply_turbo_override_or("charger", conf, cpuload, load1m)

    set_frequencies("charger")
    footer()

def set_autofreq():
    """
    set cpufreq governor based if device is charging
    """
    print("\n" + "-" * 28 + " CPU frequency scaling " + "-" * 28 + "\n")

    # determine which governor should be used
    override = get_override()
    is_charging = charging()
    if override == "default":
        print(f"Battery is: {'charging' if is_charging else 'discharging'}\n")

    profile = decide_profile(override, is_charging)
    if profile == CHARGER: set_performance()
    else: set_powersave()

def python_info():
    print("Python:", platform.python_version())
    print("psutil package:", psutil.__version__)
    print("platform package:", platform.__version__)
    print("click package:", click.__version__)
    print("distro package:", distro.__version__)

def device_info(): print("Computer type:", getoutput("dmidecode --string chassis-type"))

def distro_info():
    dist = "UNKNOWN distro"
    version = "UNKNOWN version"
    if IS_INSTALLED_WITH_SNAP:
        try:
            with open("/var/lib/snapd/hostfs/etc/os-release", "r") as searchfile:
                for line in searchfile:
                    if line.startswith("NAME="):
                        dist = line[5 : line.find("$")].strip('"')
                        continue
                    elif line.startswith("VERSION="):
                        version = line[8 : line.find("$")].strip('"')
                        continue
        except PermissionError as e: print(repr(e))
        dist = f"{dist} {version}"
    else: # get distro information
        fdist = distro.linux_distribution()
        dist = " ".join(x for x in fdist)

    print("Linux distro: " + dist)
    print("Linux kernel: " + platform.release())

def sysinfo():
    """
    get system information
    """
    # processor_info
    model_name = getoutput("grep -E 'model name' /proc/cpuinfo -m 1").split(":")[-1]
    print(f"Processor:{model_name}")

    # get core count
    total_cpu_count = int(getoutput("nproc"))
    print("Cores:", total_cpu_count)

    # get architecture
    cpu_arch = platform.machine()
    print("Architecture:", cpu_arch)

    # get driver
    driver = platform_sysfs.scaling_driver()
    print("Driver: " + driver)

    config_path = config.path if config.has_config() else None
    if config_path is None:
        from auto_cpufreq.config.config import find_config_file
        config_path = find_config_file(None)
    if os.path.isfile(config_path):
        print(f"\nUsing settings defined in {config_path}")

    # get usage and freq info of cpus
    usage_per_cpu = psutil.cpu_percent(interval=1, percpu=True)
    # psutil current freq not used, gives wrong values with offline cpu's
    minmax_freq_per_cpu = psutil.cpu_freq(percpu=True)

    # max and min freqs, psutil reports wrong max/min freqs with offline cores with percpu=False
    max_freq = max([freq.max for freq in minmax_freq_per_cpu])
    min_freq = min([freq.min for freq in minmax_freq_per_cpu])
    print("\n" + "-" * 30 + " Current CPU stats " + "-" * 30 + "\n")
    print(f"CPU max frequency: {max_freq:.0f} MHz")
    print(f"CPU min frequency: {min_freq:.0f} MHz\n")

    # get coreid's and frequencies of online cpus by parsing /proc/cpuinfo
    coreid_info = getoutput("grep -E 'processor|cpu MHz|core id' /proc/cpuinfo").split("\n")
    cpu_core = dict()
    freq_per_cpu = []
    for i in range(0, len(coreid_info), 3):
        # ensure that indices are within the valid range, before accessing the corresponding elements
        if i + 1 < len(coreid_info): freq_per_cpu.append(float(coreid_info[i + 1].split(":")[-1]))
        else: continue # handle the case where the index is out of range
        # ensure that indices are within the valid range, before accessing the corresponding elements
        cpu = int(coreid_info[i].split(":")[-1])
        if i + 2 < len(coreid_info):
            core = int(coreid_info[i + 2].split(":")[-1])
            cpu_core[cpu] = core
        else: continue # handle the case where the index is out of range

    online_cpu_count = len(cpu_core)
    offline_cpus = [str(cpu) for cpu in range(total_cpu_count) if cpu not in cpu_core]

    # temperatures
    temp_sensors = psutil.sensors_temperatures()
    temp_per_cpu = [float("nan")] * online_cpu_count
    try:
        # the priority for CPU temp is as follows: coretemp sensor -> sensor with CPU in the label -> acpi -> k10temp
        if "coretemp" in temp_sensors:
            # list labels in 'coretemp'
            core_temp_labels = [temp.label for temp in temp_sensors["coretemp"]]
            for i, cpu in enumerate(cpu_core):
                # get correct index in temp_sensors
                core = cpu_core[cpu]
                cpu_temp_index = core_temp_labels.index(f"Core {core}")
                temp_per_cpu[i] = temp_sensors["coretemp"][cpu_temp_index].current
        else:
            # iterate over all sensors
            for sensor in temp_sensors:
                # iterate over all temperatures in the current sensor
                for temp in temp_sensors[sensor]:
                    if ('CPU' in temp.label or 'Tctl' in temp.label) and temp.current != 0:
                        temp_per_cpu = [temp.current] * online_cpu_count
                        break
                else: continue
                break
            else:
                for sensor in ["acpitz", "k10temp", "zenpower"]:
                    if sensor in temp_sensors and temp_sensors[sensor][0].current != 0:
                        temp_per_cpu = [temp_sensors[sensor][0].current] * online_cpu_count
                        break
    except Exception as e: print(repr(e))

    print("Core\tUsage\tTemperature\tFrequency")
    for (cpu, usage, freq, temp) in zip(cpu_core, usage_per_cpu, freq_per_cpu, temp_per_cpu):
        print(f"CPU{cpu}    {usage:>5.1f}%       {temp:>3.0f} °C     {freq:>5.0f} MHz")

    if offline_cpus: print(f"\nDisabled CPUs: {','.join(offline_cpus)}")

    # print current fan speed (only if > 0)
    current_fans = list(psutil.sensors_fans())
    for current_fan in current_fans:
        fan_speed = psutil.sensors_fans()[current_fan][0].current
        if fan_speed:
            print(f"\nCPU fan speed: {fan_speed} RPM")

def read_stats():
    if os.path.isfile(auto_cpufreq_stats_path): call(["tail", "-n 50", "-f", str(auto_cpufreq_stats_path)], stderr=DEVNULL)
    footer()

# check if program (argument) is running
def is_running(program, argument):
    # iterate over all processes found by psutil
    # and find the one with name and args passed to the function
    for p in psutil.process_iter():
        try: cmd = p.cmdline()
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess, OSError): continue
        for s in filter(lambda x: program in x, cmd):
            if argument in cmd: return True

def daemon_running_msg():
    print("\n" + "-" * 24 + " auto-cpufreq running " + "-" * 30 + "\n")
    print(
        "ERROR: auto-cpufreq is running in daemon mode.\n\nMake sure to stop the daemon before running with --live or --monitor mode"
    )
    footer()

def daemon_not_running_msg():
    print("\n" + "-" * 24 + " auto-cpufreq not running " + "-" * 30 + "\n")
    print(
        "ERROR: auto-cpufreq is not running in daemon mode.\n\nMake sure to run \"sudo auto-cpufreq --install\" first"
    )
    footer()

# check if auto-cpufreq --daemon is running
def running_daemon_check():
    if is_running("auto-cpufreq", "--daemon"):
        daemon_running_msg()
        exit(1)
    elif IS_INSTALLED_WITH_SNAP and SNAP_DAEMON_CHECK == "enabled":
        daemon_running_msg()
        exit(1)

# check if auto-cpufreq --daemon is not running
def not_running_daemon_check():
    if not is_running("auto-cpufreq", "--daemon"):
        daemon_not_running_msg()
        exit(1)
    elif IS_INSTALLED_WITH_SNAP and SNAP_DAEMON_CHECK == "disabled":
        daemon_not_running_msg()
        exit(1)
