#!/bin/bash

# Disable the PSI genset driver: stop the service and remove the boot hook.
# The driver files in /data/apps/dbus-psi-genset are left in place; run
# enable.sh to turn it back on.

DEST="/data/apps/dbus-psi-genset"
SVC="/service/dbus-psi-genset"

# remove the boot hook from /data/rc.local
if [ -f /data/rc.local ]; then
    sed -i "\|bash $DEST/enable.sh|d" /data/rc.local
fi

# stop and remove the runit service
if [ -e "$SVC" ]; then
    svc -d "$SVC" 2>/dev/null
    rm -f "$SVC"
fi

# kill the driver if still running
pkill -f "dbus-psi-genset.py" 2>/dev/null

echo "dbus-psi-genset disabled. Driver files remain in $DEST."
