#!/bin/bash

# Install / refresh the custom genset GUI page on the local display (gui-v2).
#
# This patches the gui-v2 QML on the GX local display / Remote Console so the
# genset device page also shows the PSI's 12 V DC input (V/I/P) and an editable
# "DC cutoff thresholds" menu (LVD/LVDR/HVDR/HVD).
#
# Scope: LOCAL DISPLAY ONLY. The VRM web app uses a separate compiled WASM build
# that is not patched here.
#
# Target: Venus OS v3.5x gui-v2. The root fs is reverted by a firmware update,
# so enable.sh re-runs this on every boot to re-apply.

DEST="/data/apps/dbus-psi-genset"
guiBase="/opt/victronenergy/gui-v2/Victron/VenusOS"
target="$guiBase/components/PageGensetModel.qml"
src="$DEST/qml/gui-v2/3.5x/PageGensetModel.qml"
backupDir="$DEST/.gui-backup"
backup="$backupDir/PageGensetModel.qml.stock"

# gui-v2 present? (no local display / older image -> nothing to patch)
if [ ! -f "$target" ]; then
    echo "custom-gui: gui-v2 not found at $target - skipping (no local display to patch)."
    exit 0
fi

# safety: only patch a file that looks like the expected v3.5x genset model,
# so we never clobber a different Venus OS version's GUI and break it.
if ! grep -q "ac-in-genset_status" "$target"; then
    echo "custom-gui: $target does not look like the v3.5x genset page (different Venus OS version?)."
    echo "custom-gui: skipping to avoid breaking the GUI. See README to regenerate for your version."
    exit 0
fi

# make the root fs writable (reverted on firmware update; we re-apply each boot)
if [ -f /opt/victronenergy/swupdate-scripts/remount-rw.sh ]; then
    bash /opt/victronenergy/swupdate-scripts/remount-rw.sh >/dev/null 2>&1
fi

# back up the stock file once (used by custom-gui-uninstall.sh to restore)
mkdir -p "$backupDir"
if [ ! -f "$backup" ]; then
    cp "$target" "$backup"
fi

changed=0
if ! cmp -s "$src" "$target"; then
    cp "$src" "$target"
    changed=1
fi

if [ $changed -eq 1 ]; then
    if [ -d /service/gui ]; then svcPath=/service/gui; else svcPath=/service/start-gui; fi
    svc -d "$svcPath"; sleep 1; svc -u "$svcPath"
    echo "custom-gui: installed custom genset page and restarted the GUI."
else
    echo "custom-gui: already up to date."
fi
