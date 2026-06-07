#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bench diagnostic for the Offgridtec PSI inverter.

Reads every documented register/coil and prints the decoded, scaled values so
you can confirm addresses, scaling and baudrate against a real unit before
wiring up the D-Bus driver. No D-Bus involved.

Usage:
    python3 tools/psi_dump.py /dev/ttyUSB0 [baudrate] [slave_address]
    python3 tools/psi_dump.py /dev/ttyUSB0 --start    # turn inverter ON
    python3 tools/psi_dump.py /dev/ttyUSB0 --stop     # turn inverter OFF
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, "..")
_EXT = os.path.join(_ROOT, "..", "dbus-serialbattery", "ext")
sys.path.insert(0, _ROOT)
sys.path.insert(0, _EXT)

import psi  # noqa: E402
from psi import PsiInverter  # noqa: E402


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    port = sys.argv[1]
    args = sys.argv[2:]
    action = None
    for a in list(args):
        if a in ("--start", "--stop"):
            action = a
            args.remove(a)
    baud = int(args[0]) if len(args) > 0 else 9600
    address = int(args[1]) if len(args) > 1 else 1

    inv = PsiInverter(port, slave_address=address, baudrate=baud)

    if action == "--start":
        inv.set_start(True)
        print("commanded inverter ON (coil 0x000F = 1)")
        return
    if action == "--stop":
        inv.set_start(False)
        print("commanded inverter OFF (coil 0x000F = 0)")
        return

    print("== Offgridtec PSI on %s @ %d baud, slave %d ==\n" % (port, baud, address))

    data = inv.read_realtime()
    print("DC input : %6.2f V  %6.2f A  %8.1f W" % (
        data["dc_voltage"], data["dc_current"], data["dc_power"]))
    print("AC output: %6.2f V  %6.2f A  %8.1f W" % (
        data["ac_voltage"], data["ac_current"], data["ac_power"]))
    print("Temps    : inverter %.1f degC, MOSFET %.1f degC" % (
        data["inverter_temperature"], data["mosfet_temperature"]))

    status = inv.read_status()
    print("\nStatus word 0x3202 = 0x%04X" % status["raw"])
    print("  working      : %s" % status["working"])
    print("  error        : %s" % status["error"])
    print("  load level   : %s" % status["load_level"])
    print("  DC input     : %s" % status["dc_input"])
    print("  faults       : %s" % (", ".join(status["faults"]) or "none"))
    print("  over-temp    : inverter=%s mosfet=%s" % (
        status["over_temp_inverter"], status["over_temp_mosfet"]))
    print("  saving mode  : %s" % status["saving_mode"])
    print("  /StatusCode  : %d   /Error/0/Id: '%s'" % (
        psi.status_code(status), psi.error_text(status)))

    print("\nRemote-control coil 0x000F (commanded on): %s" % inv.get_start())

    print("\nCutoff thresholds [V]:")
    for name, value in inv.read_thresholds().items():
        print("  %-4s 0x%04X = %.2f" % (name, psi.THRESHOLDS[name][0], value))


if __name__ == "__main__":
    main()
