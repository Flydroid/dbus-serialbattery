#!/bin/bash

# Start the PSI genset driver. An optional serial port may be passed as the
# first argument; otherwise the driver reads PORT from config.ini.

DRIVER_DIR="$(cd "$(dirname "$0")" && pwd)"

exec python3 "$DRIVER_DIR/dbus-psi-genset.py" "$@"
