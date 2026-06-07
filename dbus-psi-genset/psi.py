# -*- coding: utf-8 -*-
"""
Offgridtec PSI inverter — Modbus-RTU client and protocol decoding.

This module is used by the dbus-psi-genset driver to read realtime data from
the inverter and to control its remote on/off coil. It reuses the
``minimalmodbus`` library vendored in the dbus-serialbattery project (the
driver entry point puts ``.../dbus-serialbattery/ext`` on ``sys.path`` so that
``import minimalmodbus`` resolves).

The pure helper functions (``decode_status``, ``status_code``, ``error_text``,
``clamp_threshold``) carry no hardware dependency and are unit-tested in
``test/test_psi_decode.py`` without a serial port present.

Modbus map (decoded from the PSI Modbus protocol PDF). All scaled values are
transmitted as the real value multiplied by 100.

  Coil — read FC01 / write FC05
    0x000F  remote control            1 = start inverter, 0 = shut down

  Discrete inputs — read FC02
    0x2000  inverter over-temperature 1 = yes
    0x2001  MOSFET over-temperature   1 = yes
    0x2009  saving mode               1 = yes

  Input registers — read FC04 (divide by 100)
    0x3108  DC input voltage   [V]
    0x3109  DC input current   [A]
    0x310A  DC input power, low word   } [W]
    0x310B  DC input power, high word  }
    0x310C  AC output voltage  [V]
    0x310D  AC output current  [A]
    0x310E  AC output power, low word  } [W]
    0x310F  AC output power, high word }
    0x3111  inverter temperature   [degC]
    0x3112  MOSFET temperature     [degC]
    0x3202  inverter status (bit field, see decode_status)

  Holding registers — read FC03 / write FC16 (divide by 100, volts)
    0x9030  LVD   low voltage disconnect
    0x9031  LVDR  low voltage reconnect
    0x9032  HVDR  high voltage reconnect
    0x9033  HVD   high voltage disconnect
"""

import time
import threading

# Hardware dependencies are optional at import time so the pure decoding
# helpers below can be imported (and unit-tested) without a serial stack.
try:
    import serial
    import minimalmodbus
except ImportError:  # pragma: no cover - exercised only on dev machines
    serial = None
    minimalmodbus = None


# --- register map ---------------------------------------------------------

COIL_REMOTE_CONTROL = 0x000F

DI_OVER_TEMP_INVERTER = 0x2000
DI_OVER_TEMP_MOSFET = 0x2001
DI_SAVING_MODE = 0x2009

IR_DC_VOLTAGE = 0x3108
IR_DC_CURRENT = 0x3109
IR_DC_POWER_LOW = 0x310A
IR_AC_VOLTAGE = 0x310C
IR_AC_CURRENT = 0x310D
IR_AC_POWER_LOW = 0x310E
IR_TEMP_INVERTER = 0x3111
IR_TEMP_MOSFET = 0x3112
IR_STATUS = 0x3202

SCALE = 100.0

# 0x3202 status bit field
STATUS_FAULT_BITS = {
    5: "output lost control",
    6: "internal HV short",
    7: "input over-current",
    8: "output voltage abnormal",
    10: "no output",
    11: "short circuit",
}
LOAD_LEVELS = {0: "light", 1: "moderate", 2: "rated", 3: "overload"}
DC_INPUT_STATUS = {0: "ok", 1: "LVD", 2: "HVD", 3: "other"}

# Genset /StatusCode values (com.victronenergy.genset):
#   0 = Standby, 8 = Running, 10 = Error
STATUS_STANDBY = 0
STATUS_RUNNING = 8
STATUS_ERROR = 10

# DC cutoff thresholds: name -> (register, default_v, min_v, max_v).
# Ranges are the modifiable ranges from the spec for the 12 V model.
THRESHOLDS = {
    "LVD": (0x9030, 10.8, 10.3, 11.3),
    "LVDR": (0x9031, 12.5, 12.0, 13.0),
    "HVDR": (0x9032, 16.0, 15.5, 16.0),
    "HVD": (0x9033, 14.5, 14.0, 15.0),
}


# --- pure helpers (no hardware) -------------------------------------------

def decode_status(word):
    """Decode the 0x3202 status word into a dict of human-readable fields."""
    return {
        "working": bool(word & (1 << 0)),
        "error": bool(word & (1 << 1)),
        "faults": [name for bit, name in sorted(STATUS_FAULT_BITS.items()) if word & (1 << bit)],
        "load_level": LOAD_LEVELS[(word >> 12) & 0x3],
        "dc_input": DC_INPUT_STATUS[(word >> 14) & 0x3],
        "raw": word,
    }


def status_code(decoded):
    """Map a decoded status dict to a genset /StatusCode value."""
    if decoded.get("error"):
        return STATUS_ERROR
    return STATUS_RUNNING if decoded.get("working") else STATUS_STANDBY


def error_text(decoded):
    """Build the /Error/0/Id string from faults and over-temperature flags."""
    parts = list(decoded.get("faults", []))
    if decoded.get("over_temp_inverter"):
        parts.append("inverter over-temperature")
    if decoded.get("over_temp_mosfet"):
        parts.append("MOSFET over-temperature")
    return ", ".join(parts)


def clamp_threshold(name, value):
    """Clamp a threshold value to the spec-allowed range for that register."""
    _, _, lo, hi = THRESHOLDS[name]
    return max(lo, min(hi, value))


# --- Modbus client --------------------------------------------------------

class PsiInverter:
    """Talks Modbus RTU to a single Offgridtec PSI inverter."""

    def __init__(self, port, slave_address=1, baudrate=9600, timeout=0.5, retries=3):
        if minimalmodbus is None:
            raise RuntimeError("minimalmodbus is not importable; check sys.path setup")
        self.port = port
        self.slave_address = slave_address
        self.baudrate = baudrate
        self.timeout = timeout
        self.retries = retries
        self._lock = threading.Lock()
        self._mb = self._make_instrument()

    def _make_instrument(self):
        mb = minimalmodbus.Instrument(
            self.port,
            slaveaddress=self.slave_address,
            mode="rtu",
            close_port_after_each_call=True,
            debug=False,
        )
        mb.serial.baudrate = self.baudrate
        mb.serial.bytesize = 8
        mb.serial.parity = minimalmodbus.serial.PARITY_NONE
        mb.serial.stopbits = serial.STOPBITS_ONE
        mb.serial.timeout = self.timeout
        return mb

    def _retry(self, fn):
        last = None
        for _ in range(self.retries):
            try:
                return fn()
            except Exception as exc:  # noqa: BLE001 - re-raised after retries
                last = exc
                time.sleep(0.05)
        raise last

    def _read_u32(self, low_address):
        """Read a 32-bit value stored as [low word, high word]."""
        regs = self._retry(lambda: self._mb.read_registers(low_address, 2, functioncode=4))
        return regs[0] | (regs[1] << 16)

    # -- connection --------------------------------------------------------

    def test_connection(self):
        """Read the status register to confirm a PSI is responding."""
        try:
            with self._lock:
                self._retry(lambda: self._mb.read_register(IR_STATUS, 0, functioncode=4))
            return True
        except Exception:  # noqa: BLE001 - probing, failure is expected/normal
            return False

    # -- realtime data -----------------------------------------------------

    def read_realtime(self):
        """Return scaled DC/AC measurements and temperatures."""
        with self._lock:
            dc_v = self._retry(lambda: self._mb.read_register(IR_DC_VOLTAGE, 0, functioncode=4)) / SCALE
            dc_a = self._retry(lambda: self._mb.read_register(IR_DC_CURRENT, 0, functioncode=4)) / SCALE
            dc_w = self._read_u32(IR_DC_POWER_LOW) / SCALE
            ac_v = self._retry(lambda: self._mb.read_register(IR_AC_VOLTAGE, 0, functioncode=4)) / SCALE
            ac_a = self._retry(lambda: self._mb.read_register(IR_AC_CURRENT, 0, functioncode=4)) / SCALE
            ac_w = self._read_u32(IR_AC_POWER_LOW) / SCALE
            inv_t = self._retry(lambda: self._mb.read_register(IR_TEMP_INVERTER, 0, functioncode=4, signed=True)) / SCALE
            mos_t = self._retry(lambda: self._mb.read_register(IR_TEMP_MOSFET, 0, functioncode=4, signed=True)) / SCALE
        return {
            "dc_voltage": dc_v,
            "dc_current": dc_a,
            "dc_power": dc_w,
            "ac_voltage": ac_v,
            "ac_current": ac_a,
            "ac_power": ac_w,
            "inverter_temperature": inv_t,
            "mosfet_temperature": mos_t,
        }

    def read_status(self):
        """Read and decode the status register plus the over-temp/mode inputs."""
        with self._lock:
            word = self._retry(lambda: self._mb.read_register(IR_STATUS, 0, functioncode=4))
            over_temp_inv = self._retry(lambda: self._mb.read_bit(DI_OVER_TEMP_INVERTER, functioncode=2))
            over_temp_mos = self._retry(lambda: self._mb.read_bit(DI_OVER_TEMP_MOSFET, functioncode=2))
            saving = self._retry(lambda: self._mb.read_bit(DI_SAVING_MODE, functioncode=2))
        decoded = decode_status(word)
        decoded["over_temp_inverter"] = bool(over_temp_inv)
        decoded["over_temp_mosfet"] = bool(over_temp_mos)
        decoded["saving_mode"] = bool(saving)
        return decoded

    # -- remote control ----------------------------------------------------

    def get_start(self):
        """Read the remote-control coil (True = inverter commanded on)."""
        with self._lock:
            return bool(self._retry(lambda: self._mb.read_bit(COIL_REMOTE_CONTROL, functioncode=1)))

    def set_start(self, on):
        """Start (True) or shut down (False) the inverter via the coil."""
        with self._lock:
            self._retry(lambda: self._mb.write_bit(COIL_REMOTE_CONTROL, 1 if on else 0, functioncode=5))

    # -- cutoff thresholds -------------------------------------------------

    def read_thresholds(self):
        """Read the four DC cutoff thresholds (volts)."""
        out = {}
        with self._lock:
            for name, (reg, *_rest) in THRESHOLDS.items():
                out[name] = self._retry(lambda r=reg: self._mb.read_register(r, 0, functioncode=3)) / SCALE
        return out

    def write_threshold(self, name, value):
        """Clamp and write one threshold (volts). Returns the value written."""
        if name not in THRESHOLDS:
            raise ValueError("unknown threshold: %s" % name)
        clamped = clamp_threshold(name, float(value))
        reg = THRESHOLDS[name][0]
        raw = int(round(clamped * SCALE))
        with self._lock:
            self._retry(lambda: self._mb.write_register(reg, raw, 0, functioncode=16))
        return clamped
