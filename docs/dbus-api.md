# D-Bus API

auto-cpufreq exposes a D-Bus interface on the system bus for client apps. The interface description is in [`scripts/org.autocpufreq.Daemon.xml`](../scripts/org.autocpufreq.Daemon.xml).

| | |
|---|---|
| Bus | system |
| Name | `org.autocpufreq.Daemon` |
| Object path | `/org/autocpufreq/Daemon` |
| Interface | `org.autocpufreq.Daemon` |
| API version | `1` (from `GetStatus`) |

## Setup and access

Install the interface with `sudo auto-cpufreq --install-dbus-interface` and remove it with `sudo auto-cpufreq --remove-dbus-interface`. Install adds the invoking user to the `auto-cpufreq` group, which is the only group allowed to call the interface. The user has to log out and back in before the group applies. The snap package doesn't support the interface.

The service is started by the bus on the first call and exits after 5 minutes without calls. There are no signals, so clients poll (for example `GetReport` every 1–2 seconds while visible).

A client can tell these states apart:

| Error on first call | Meaning | Fix |
|---|---|---|
| `org.freedesktop.DBus.Error.ServiceUnknown` | Interface not installed | `sudo auto-cpufreq --install-dbus-interface` |
| `org.freedesktop.DBus.Error.AccessDenied` | User isn't in the `auto-cpufreq` group | `sudo usermod -aG auto-cpufreq $USER`, then log in again |
| `daemon_running` is false in `GetStatus` | auto-cpufreq daemon isn't running | `sudo auto-cpufreq --install` |

## Errors

| Name | When |
|---|---|
| `org.autocpufreq.Error.InvalidArgument` | A value or key was rejected. The message says why and can be shown to the user. |
| `org.autocpufreq.Error.Failed` | The action was valid but couldn't be done, for example a file couldn't be written. |
| `org.autocpufreq.Error.NotSupported` | The config file is read-only, so `SetConfigSection`, `SetIgnoreList` and `SetBatteryConfig` can't change it. This happens on NixOS, where the config is generated from `programs.auto-cpufreq.settings`. |

## Value conventions

- Every `a{sv}` result leaves out keys whose value is unknown or unsupported on the machine. Treat every key as optional unless marked *always*.
- Config values are sent and returned as strings, exactly as written in the config file.
- In `Set*` calls that take `a{ss}`, an empty string removes the key from the config (it's commented out). Keys that aren't passed are left as they are.

## Methods

### GetStatus → `a{sv}`

| Key | Type | |
|---|---|---|
| `api_version` | `i` | *always* |
| `daemon_running` | `b` | *always* |
| `config_path` | `s` | *always* |
| `version` | `s` | auto-cpufreq version |

### GetReport → `a{sv}`

| Key | Type | |
|---|---|---|
| `distro_name`, `distro_version`, `arch`, `processor_model`, `kernel_version`, `cpu_driver` | `s` | *always* |
| `total_cores` | `i` | |
| `governor` | `s` | current scaling governor |
| `epp` | `s` | current energy performance preference |
| `epb` | `s` | current energy perf bias, by name (e.g. `balance_power`) |
| `hwp_dynamic_boost` | `b` | |
| `fan_rpm` | `i` | |
| `cpu_usage` | `d` | percent, *always* |
| `cpu_min_freq_mhz`, `cpu_max_freq_mhz` | `d` | MHz |
| `load` | `d` | *always* |
| `load_avg` | `ad` | 1, 5 and 15 minute load average |
| `avg_temp` | `d` | °C |
| `turbo_on` | `b` | |
| `turbo_amd_auto` | `b` | AMD P-state auto boost |
| `offline_cpus` | `ai` | *always* |
| `platform_profile` | `s` | current platform profile |
| `cores` | `aa{sv}` | *always*, one dict per core: `id` (`i`), `usage` (`d`, percent), `temperature` (`d`, °C), `frequency_mhz` (`d`) |
| `battery` | `a{sv}` | *always*, same as `GetBattery` |

### GetBattery → `a{sv}`

| Key | Type | |
|---|---|---|
| `present` | `b` | *always* |
| `status` | `s` | *always*: `charging`, `discharging`, `not-charging`, `full` or `unknown` |
| `name` | `s` | e.g. `BAT0` |
| `level` | `i` | percent |
| `is_charging`, `is_ac_plugged` | `b` | |
| `power_watts` | `d` | |
| `start_threshold`, `stop_threshold` | `i` | current hardware charge thresholds, percent |

### GetOverrides → `a{sv}`

| Key | Type | |
|---|---|---|
| `governor_override` | `s` | *always*: `auto`, `performance` or `powersave` |
| `turbo_override` | `s` | *always*: `auto`, `always` or `never` |
| `active_governor` | `s` | governor in use right now |
| `turbo_on` | `b` | |

### GetConfig → `a{sv}`

| Key | Type | |
|---|---|---|
| `path` | `s` | *always* |
| `exists` | `b` | *always* |
| `writable` | `b` | *always*, false when the config can't be edited over D-Bus (for example on NixOS), so show it read-only |
| `charger`, `battery` | `a{ss}` | *always*, the `[charger]` and `[battery]` sections |
| `ignore_list` | `as` | *always*, the `[power_supply_ignore_list]` names |
| `bluetooth_boot` | `b` | whether Bluetooth turns on at boot |
| `error` | `s` | set when the config file couldn't be parsed |

### GetBatteryConfig → `a{sv}`

Charge settings from the `[battery]` section.

| Key | Type | |
|---|---|---|
| `enable_thresholds` | `b` | *always*, master switch for both thresholds and conservation mode |
| `battery_device` | `s` | |
| `start_threshold`, `stop_threshold` | `i` | percent |
| `conservation_mode` | `b` | `ideapad_laptop_conservation_mode` |

### GetCapabilities → `a{sv}`

What the machine supports. Use it to fill choices and hide controls.

| Key | Type | |
|---|---|---|
| `governors` | `as` | *always* |
| `epp_choices` | `as` | *always*, empty if EPP isn't supported |
| `epb` | `b` | *always* |
| `hwp_dynamic_boost` | `b` | *always* |
| `platform_profiles` | `as` | *always* |
| `platform_profile_writable` | `b` | *always* |
| `hw_min_freq_khz`, `hw_max_freq_khz` | `i` | kHz, the limits for `scaling_min_freq` and `scaling_max_freq` |
| `turbo` | `b` | *always* |
| `power_supplies` | `aa{sv}` | *always*, one dict per supply: `name` (`s`), `type` (`s`, e.g. `Battery`, `Mains`, `USB`) |
| `batteries` | `as` | *always*, names that can be used as `battery_device` |
| `charge_control` | `s` | *always*: `thresholds`, `conservation` (IdeaPad) or `none` |
| `bluetooth` | `b` | *always*, whether `SetBluetoothBoot` can be used |

### SetGovernorOverride(`s` value)

`auto`, `performance` or `powersave`. `auto` removes the override.

### SetTurboOverride(`s` value)

`auto`, `always` or `never`.

Both setters only store the override. The daemon applies it on its next cycle, a few seconds later, so `active_governor` and `turbo_on` in `GetOverrides` can still show the old state right after the call.

### ResetOverrides()

Sets both overrides back to `auto`.

### SetConfigSection(`s` section, `a{ss}` values)

`section` is `charger` or `battery`. The running daemon picks up the change on its own.

| Key | Accepted value |
|---|---|
| `governor` | one of `governors` |
| `energy_performance_preference` | one of `epp_choices` |
| `energy_perf_bias` | `0`–`15` or an EPB name |
| `platform_profile` | one of `platform_profiles` |
| `turbo` | `auto`, `always` or `never` |
| `hwp_dynamic_boost`, `enforce_platform_profile` | `true` or `false` |
| `scaling_min_freq`, `scaling_max_freq` | kHz within the hardware limits, min lower than max |

### SetIgnoreList(`as` names)

Replaces the whole `[power_supply_ignore_list]`. It applies to both charger and battery.

### SetBatteryConfig(`a{ss}` values)

Writes charge settings to `[battery]` and applies them to the hardware right away.

| Key | Accepted value |
|---|---|
| `enable_thresholds` | `true` or `false`. When `false`, thresholds are reset to 0/100 and conservation mode is turned off. |
| `battery_device` | one of `batteries` |
| `start_threshold` | `0`–`99`, lower than `stop_threshold` |
| `stop_threshold` | `1`–`100` |
| `ideapad_laptop_conservation_mode` | `true` or `false` |

Thresholds are only used when `charge_control` is `thresholds`, and conservation mode only when it's `conservation`.

### SetBluetoothBoot(`b` enabled)

Sets whether Bluetooth turns on at boot in `/etc/bluetooth/main.conf`. Only offer it when `bluetooth` is true in `GetCapabilities`.
