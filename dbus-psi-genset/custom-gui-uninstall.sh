#!/bin/bash

# Restore the stock gui-v2 genset page (undo custom-gui-install.sh).

DEST="/data/apps/dbus-psi-genset"
guiBase="/opt/victronenergy/gui-v2/Victron/VenusOS"
target="$guiBase/components/PageGensetModel.qml"
backup="$DEST/.gui-backup/PageGensetModel.qml.stock"

if [ ! -f "$backup" ]; then
    echo "custom-gui: no backup found ($backup); nothing to restore."
    exit 0
fi

if [ -f /opt/victronenergy/swupdate-scripts/remount-rw.sh ]; then
    bash /opt/victronenergy/swupdate-scripts/remount-rw.sh >/dev/null 2>&1
fi

if [ -f "$target" ]; then
    cp "$backup" "$target"
    if [ -d /service/gui ]; then svcPath=/service/gui; else svcPath=/service/start-gui; fi
    svc -d "$svcPath"; sleep 1; svc -u "$svcPath"
    echo "custom-gui: restored stock genset page and restarted the GUI."
fi
