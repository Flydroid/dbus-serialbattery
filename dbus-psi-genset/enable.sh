#!/bin/bash

# Enable / re-enable the PSI genset driver.
#
# Run by install.sh, and re-run automatically on every boot via /data/rc.local.
# A Venus OS firmware update reflashes the root filesystem (wiping /service),
# but leaves /data intact -- so this script recreates the runit service on the
# (possibly freshly flashed) root fs each boot. That makes the driver survive
# firmware updates with no manual reinstall.

DEST="/data/apps/dbus-psi-genset"
SVC="/service/dbus-psi-genset"

# the driver reuses minimalmodbus + velib_python from dbus-serialbattery
if [ ! -d "/data/apps/dbus-serialbattery/ext/velib_python" ]; then
    echo "ERROR: /data/apps/dbus-serialbattery is required (provides minimalmodbus + velib_python)."
    exit 1
fi

# fix permissions (modes are lost if the folder was restored from a tar)
chmod +x "$DEST"/*.sh "$DEST"/*.py "$DEST"/service/run "$DEST"/service/log/run 2>/dev/null

# (re)create the runit service symlink on the (possibly freshly flashed) root fs
ln -sfn "$DEST/service" "$SVC"

# register self in /data/rc.local so this runs again after a firmware update.
# /data/rc.local lives on the persistent partition and is executed on every
# boot, including the first boot after an update.
filename=/data/rc.local
if [ ! -f "$filename" ]; then
    echo "#!/bin/bash" > "$filename"
    chmod 755 "$filename"
fi
hook="bash $DEST/enable.sh > $DEST/startup.log 2>&1 &"
grep -qxF "$hook" "$filename" || echo "$hook" >> "$filename"

# restart the service if it is already supervised; otherwise runsvdir will pick
# up the new symlink within a few seconds and start it.
[ -e "$SVC/supervise" ] && svc -t "$SVC" 2>/dev/null

echo "dbus-psi-genset enabled (service $SVC, serial port read from $DEST/config.ini)."
