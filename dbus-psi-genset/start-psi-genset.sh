#!/bin/bash

# Start the PSI genset driver. The serial port is provided as the first
# argument (e.g. by the runit service below), defaulting to /dev/ttyUSB0.

DRIVER_DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${1:-/dev/ttyUSB0}"

exec python3 "$DRIVER_DIR/dbus-psi-genset.py" "$PORT"
