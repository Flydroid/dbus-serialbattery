#!/bin/bash

# Install the PSI genset driver on Venus OS.
#
#   1. copies this folder to /data/apps/dbus-psi-genset (the persistent
#      partition, which survives firmware updates)
#   2. creates config.ini from config.sample.ini if missing
#   3. runs enable.sh, which creates the runit service and registers a
#      /data/rc.local hook so the driver is restored automatically after a
#      Venus OS firmware update -- no manual reinstall needed
#
# Set the serial port via PORT= in config.ini. Usage:  ./install.sh
#
# The dbus-serialbattery project must also be present at
# /data/apps/dbus-serialbattery (this driver reuses its vendored
# minimalmodbus and velib_python libraries).

set -e

SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="/data/apps/dbus-psi-genset"

if [ ! -d "/data/apps/dbus-serialbattery/ext/velib_python" ]; then
    echo "ERROR: /data/apps/dbus-serialbattery is required (provides minimalmodbus + velib_python)."
    exit 1
fi

# copy the driver to the persistent partition (skip if already running from there)
if [ "$SRC" != "$DEST" ]; then
    mkdir -p "$DEST"
    cp -r "$SRC/." "$DEST/"
fi

if [ ! -f "$DEST/config.ini" ]; then
    cp "$DEST/config.sample.ini" "$DEST/config.ini"
    echo "created $DEST/config.ini - review it (PORT, baudrate, slave address, thresholds)"
fi

bash "$DEST/enable.sh"

echo
echo "installed. Set the serial port via PORT= in $DEST/config.ini, then re-run"
echo "$DEST/enable.sh to apply changes."
echo "Check the log with: tail -f /var/log/dbus-psi-genset/current | tai64nlocal"
