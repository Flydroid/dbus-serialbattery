#!/bin/bash

# Install the PSI genset driver on Venus OS.
#
#   1. copies this folder to /data/apps/dbus-psi-genset
#   2. creates config.ini from config.sample.ini if missing
#   3. installs a runit service bound to the given serial port
#
# Usage:  ./install.sh ttyUSB0
#
# The dbus-serialbattery project must also be present at
# /data/apps/dbus-serialbattery (this driver reuses its vendored
# minimalmodbus and velib_python libraries).

set -e

TTY="${1:-ttyUSB0}"
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="/data/apps/dbus-psi-genset"
SVC="/service/dbus-psi-genset"

if [ ! -d "/data/apps/dbus-serialbattery/ext/velib_python" ]; then
    echo "ERROR: /data/apps/dbus-serialbattery is required (provides minimalmodbus + velib_python)."
    exit 1
fi

mkdir -p "$DEST"
cp -r "$SRC/." "$DEST/"

if [ ! -f "$DEST/config.ini" ]; then
    cp "$DEST/config.sample.ini" "$DEST/config.ini"
    echo "created $DEST/config.ini - review it (baudrate, slave address, thresholds)"
fi

# bind the service to the requested tty
sed "s/TTY/$TTY/g" "$DEST/service/run" > "$DEST/service/run.tmp"
mv "$DEST/service/run.tmp" "$DEST/service/run"
chmod +x "$DEST/service/run" "$DEST/service/log/run" "$DEST/start-psi-genset.sh"

ln -sfn "$DEST/service" "$SVC"

echo "installed. service linked at $SVC for /dev/$TTY"
echo "check the log with: tail -f /var/log/dbus-psi-genset/current | tai64nlocal"
