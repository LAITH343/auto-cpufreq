import os
import sys

# D-Bus activation starts the service without PATH, and auto-cpufreq runs shell tools at import time.
if not os.environ.get("PATH"):
    os.environ["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

from auto_cpufreq.dbus.service import main

sys.exit(main())
