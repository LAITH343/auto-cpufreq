inputs:
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.programs.auto-cpufreq;
  inherit (pkgs.stdenv.hostPlatform) system;
  defaultPackage = inputs.self.packages.${system}.default;
  cfgFilename = "auto-cpufreq.conf";
  cfgFile = format.generate cfgFilename cfg.settings;

  inherit (lib) types;
  inherit (lib.modules) mkIf mkForce;
  inherit (lib.options) mkOption mkEnableOption;

  format = pkgs.formats.ini { };

  dbusName = "org.autocpufreq.Daemon";
  dbusGroup = "auto-cpufreq";
  dbusPython = defaultPackage.pythonModule.withPackages (_: [ defaultPackage ]);
  dbusFiles = pkgs.symlinkJoin {
    name = "auto-cpufreq-dbus";
    paths = [
      (pkgs.writeTextDir "share/dbus-1/system.d/${dbusName}.conf" ''
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-BUS Bus Configuration 1.0//EN"
         "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
        <busconfig>
          <policy user="root">
            <allow own="${dbusName}"/>
            <allow send_destination="${dbusName}"/>
          </policy>
          <policy group="${dbusGroup}">
            <allow send_destination="${dbusName}"/>
          </policy>
          <policy context="default">
            <deny own="${dbusName}"/>
            <deny send_destination="${dbusName}"/>
          </policy>
        </busconfig>
      '')
      (pkgs.writeTextDir "share/dbus-1/system-services/${dbusName}.service" ''
        [D-BUS Service]
        Name=${dbusName}
        Exec=${pkgs.coreutils}/bin/false
        User=root
        SystemdService=auto-cpufreq-dbus.service
      '')
    ];
  };
in
{
  options.programs.auto-cpufreq = {
    enable = mkEnableOption "Automatic CPU speed & power optimizer for Linux";

    settings = mkOption {
      description = ''
        Configuration for `auto-cpufreq`.

        See its [example configuration file] for supported settings.
        [example configuration file]: https://github.com/AdnanHodzic/auto-cpufreq/blob/master/auto-cpufreq.conf-example
      '';

      default = { };
      type = types.submodule { freeformType = format.type; };
    };

    dbusInterface.enable = mkEnableOption ''
      the D-Bus interface for client apps. Users in the `${dbusGroup}` group can use it.
      Config edits over D-Bus are not supported, since the config is generated from `settings`
    '';
  };

  config = mkIf cfg.enable {
    environment.systemPackages = [ defaultPackage ];

    systemd = {
      packages = [ defaultPackage ];
      services.auto-cpufreq = {
        wantedBy = [ "multi-user.target" ];
        path = with pkgs; [
          bash
          coreutils
          gawk
        ];
        overrideStrategy = "asDropin";

        serviceConfig.WorkingDirectory = "";
        serviceConfig.ExecStart = mkForce [
          ""
          "${defaultPackage}/bin/auto-cpufreq --daemon --config ${cfgFile}"
        ];
      };

      services.auto-cpufreq-dbus = mkIf cfg.dbusInterface.enable {
        description = "auto-cpufreq D-Bus interface";
        path = with pkgs; [
          defaultPackage
          bash
          gawk
          getent
          kmod
          dmidecode
        ];
        serviceConfig = {
          Type = "dbus";
          BusName = dbusName;
          ExecStart = "${dbusPython}/bin/python -m auto_cpufreq.dbus --config ${cfgFile}";
        };
      };
    };

    services.dbus.packages = mkIf cfg.dbusInterface.enable [ dbusFiles ];
    users.groups.${dbusGroup} = mkIf cfg.dbusInterface.enable { };

    assertions = [
      {
        assertion = !config.services.power-profiles-daemon.enable;
        message = ''
          You have set services.power-profiles-daemon.enable = true;
          which conflicts with auto-cpufreq
        '';
      }
    ];
  };
}
