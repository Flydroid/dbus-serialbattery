#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dbus-psi-genset — Venus OS D-Bus driver for the Offgridtec PSI inverter.

The PSI is wired to the AC-in of a MultiPlus-II and acts as a 230 VAC
generator. This driver registers a ``com.victronenergy.genset`` service so the
inverter shows up under "Generator" in the GX, publishes its live AC + 12 V DC
data, and exposes a writable ``/Start`` path that toggles the PSI's Modbus
remote-control coil (manual control — GX auto start/stop is intentionally not
used). See README.md and the bundled config.sample.ini.

Usage:
    python3 dbus-psi-genset.py [/dev/ttyUSBx]

The serial port may be given on the command line (as the serial-starter does)
or via PORT in config.ini.
"""

import os
import sys
import logging
import configparser

# Reuse the libraries vendored in the sibling dbus-serialbattery project rather
# than duplicating them: minimalmodbus and the velib_python D-Bus helpers.
_HERE = os.path.dirname(os.path.abspath(__file__))
_EXT = os.path.join(_HERE, "..", "dbus-serialbattery", "ext")
sys.path.insert(0, _HERE)
sys.path.insert(0, _EXT)
sys.path.insert(0, os.path.join(_EXT, "velib_python"))

import dbus  # noqa: E402
from dbus.mainloop.glib import DBusGMainLoop  # noqa: E402

try:
    from gi.repository import GLib  # noqa: E402
except ImportError:
    import gobject as GLib  # noqa: E402  (older Venus OS)

from vedbus import VeDbusService  # noqa: E402
from settingsdevice import SettingsDevice  # noqa: E402

import psi  # noqa: E402
from psi import PsiInverter  # noqa: E402

DRIVER_VERSION = "0.1.0"
# Victron "Virtual AC genset" product id. Using a recognised genset product id
# makes the GX GUI render the proper genset device page (PageGensetModel)
# instead of falling back to a generic AC-input page.
PRODUCT_ID = 0xC06B
THRESHOLD_NAMES = ("LVD", "LVDR", "HVDR", "HVD")

# Live measurement/status paths. They are cleared to None (D-Bus "invalid", so
# the GX shows no value) whenever the inverter is unreachable, so stale readings
# are never displayed alongside /Connected = 0.
DYNAMIC_PATHS = (
    "/Ac/L1/Voltage",
    "/Ac/L1/Current",
    "/Ac/L1/Power",
    "/Ac/Power",
    "/Dc/0/Voltage",
    "/Dc/0/Current",
    "/Dc/0/Power",
    "/StarterVoltage",
    "/Engine/WindingTemperature",
    "/Engine/CoolantTemperature",
    "/StatusCode",
    "/Error/0/Id",
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("dbus-psi-genset")


def get_bus():
    return dbus.SessionBus() if "DBUS_SESSION_BUS_ADDRESS" in os.environ else dbus.SystemBus()


def load_config():
    config = configparser.ConfigParser()
    path = os.path.join(_HERE, "config.ini")
    if os.path.isfile(path):
        config.read(path)
    else:
        logger.warning("config.ini not found, using built-in defaults")
    return config["DEFAULT"]


class PsiGensetService:
    def __init__(self, port, cfg, bus):
        self.port = port
        self.cfg = cfg
        self.bus = bus
        self.poll_interval = int(cfg.get("POLL_INTERVAL", "2"))
        self.ac_frequency = float(cfg.get("AC_FREQUENCY", "50"))
        self.manage_thresholds = cfg.get("MANAGE_THRESHOLDS", "false").strip().lower() == "true"

        self.psi = PsiInverter(
            port,
            slave_address=int(cfg.get("SLAVE_ADDRESS", "1")),
            baudrate=int(cfg.get("BAUDRATE", "9600")),
        )

        if not self.psi.test_connection():
            raise RuntimeError("no PSI inverter responding on %s" % port)
        logger.info("PSI inverter found on %s", port)

        self.service = self._create_service()

    # -- D-Bus service setup ----------------------------------------------

    def _device_instance(self):
        """Allocate/persist a VRM device instance via com.victronenergy.settings."""
        portname = self.port.split("/")[-1]
        settings = SettingsDevice(
            self.bus,
            {"instance": ["/Settings/Devices/psi_%s/ClassAndVrmInstance" % portname, "genset:40", 0, 0]},
            eventCallback=None,
        )
        class_and_instance = settings["instance"]
        return int(str(class_and_instance).split(":")[1])

    def _create_service(self):
        portname = self.port.split("/")[-1]
        name = "com.victronenergy.genset.psi_%s" % portname
        service = VeDbusService(name, self.bus, register=False)

        service.add_mandatory_paths(
            processname=__file__,
            processversion=DRIVER_VERSION,
            connection="Modbus RTU on %s" % self.port,
            deviceinstance=self._device_instance(),
            productid=PRODUCT_ID,
            productname=self.cfg.get("PRODUCT_NAME", "Offgridtec PSI"),
            firmwareversion=DRIVER_VERSION,
            hardwareversion="Offgridtec PSI",
            connected=1,
        )

        # AC output (single phase)
        service.add_path("/Ac/L1/Voltage", None)
        service.add_path("/Ac/L1/Current", None)
        service.add_path("/Ac/L1/Power", None)
        service.add_path("/Ac/Power", None)
        service.add_path("/Ac/Frequency", self.ac_frequency)
        service.add_path("/NrOfPhases", 1)

        # DC input (12 V side)
        service.add_path("/Dc/0/Voltage", None)
        service.add_path("/Dc/0/Current", None)
        service.add_path("/Dc/0/Power", None)
        service.add_path("/StarterVoltage", None)

        # Status / faults
        service.add_path("/StatusCode", psi.STATUS_STANDBY)
        service.add_path("/Error/0/Id", "")
        service.add_path("/Engine/WindingTemperature", None)
        service.add_path("/Engine/CoolantTemperature", None)

        # Manual remote start/stop
        service.add_path("/RemoteStartModeEnabled", 1)
        service.add_path("/Start", 0, writeable=True, onchangecallback=self._on_start_change)

        if self.manage_thresholds:
            self._setup_thresholds(service)

        service.register()
        logger.info("registered %s", name)
        return service

    def _setup_thresholds(self, service):
        # Apply configured thresholds to the inverter, then expose them writable.
        for name in THRESHOLD_NAMES:
            if name in self.cfg:
                try:
                    written = self.psi.write_threshold(name, float(self.cfg[name]))
                    logger.info("set PSI %s = %.2f V", name, written)
                except Exception as exc:  # noqa: BLE001
                    logger.error("failed to write %s: %s", name, exc)
        try:
            current = self.psi.read_thresholds()
        except Exception as exc:  # noqa: BLE001
            logger.error("failed to read thresholds: %s", exc)
            current = {}
        for name in THRESHOLD_NAMES:
            service.add_path(
                "/Settings/%s" % name,
                current.get(name),
                writeable=True,
                onchangecallback=self._make_threshold_cb(name),
            )

    # -- write callbacks ---------------------------------------------------

    def _on_start_change(self, path, value):
        try:
            self.psi.set_start(bool(value))
            logger.info("/Start -> %s (coil 0x000F)", int(bool(value)))
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("failed to set /Start: %s", exc)
            return False

    def _make_threshold_cb(self, name):
        def cb(path, value):
            try:
                written = self.psi.write_threshold(name, float(value))
            except Exception as exc:  # noqa: BLE001
                logger.error("failed to write %s: %s", name, exc)
                return False
            # Reflect the clamped value back on D-Bus (does not re-trigger cb).
            if written != float(value):
                GLib.idle_add(lambda: self.service.__setitem__(path, written) or False)
            return True
        return cb

    # -- polling -----------------------------------------------------------

    def _clear_values(self):
        """Invalidate all live paths so the GX shows no data when offline."""
        for path in DYNAMIC_PATHS:
            self.service[path] = None

    def update(self):
        try:
            data = self.psi.read_realtime()
            status = self.psi.read_status()
        except Exception as exc:  # noqa: BLE001
            logger.warning("read failed: %s", exc)
            # Only act on the transition to offline: zero /Connected and blank
            # the live values once, instead of re-writing them every cycle.
            if self.service["/Connected"] != 0:
                self.service["/Connected"] = 0
                self._clear_values()
            return True

        s = self.service
        s["/Connected"] = 1
        s["/Ac/L1/Voltage"] = round(data["ac_voltage"], 2)
        s["/Ac/L1/Current"] = round(data["ac_current"], 2)
        s["/Ac/L1/Power"] = round(data["ac_power"], 1)
        s["/Ac/Power"] = round(data["ac_power"], 1)
        s["/Dc/0/Voltage"] = round(data["dc_voltage"], 2)
        s["/Dc/0/Current"] = round(data["dc_current"], 2)
        s["/Dc/0/Power"] = round(data["dc_power"], 1)
        s["/StarterVoltage"] = round(data["dc_voltage"], 2)
        s["/Engine/WindingTemperature"] = round(data["inverter_temperature"], 1)
        s["/Engine/CoolantTemperature"] = round(data["mosfet_temperature"], 1)
        s["/StatusCode"] = psi.status_code(status)
        s["/Error/0/Id"] = psi.error_text(status)
        return True


def main():
    DBusGMainLoop(set_as_default=True)
    cfg = load_config()
    port = sys.argv[1] if len(sys.argv) > 1 else cfg.get("PORT", "/dev/ttyUSB0")
    bus = get_bus()

    svc = PsiGensetService(port, cfg, bus)
    GLib.timeout_add(svc.poll_interval * 1000, svc.update)

    logger.info("polling %s every %ss", port, svc.poll_interval)
    GLib.MainLoop().run()


if __name__ == "__main__":
    main()
