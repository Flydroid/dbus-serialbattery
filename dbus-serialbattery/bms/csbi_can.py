# -*- coding: utf-8 -*-

# CSBI CAN BMS implementation for dbus-serialbattery
#
# Supports:
#   - Cell voltages (C-channel, 0x050–0x055): 24 logical cells across two 12S half-modules (2P12S)
#   - Temperatures (0x450–0x453): cell NTC, PCB NTC, IC die temps
#   - BMS status frame (0x010): contactor state, fault latch, balancing, SM faults
#   - Fault frames (0x020): per-cell/sensor UV/OV/UT/OT and hardware SM faults
#   - Contactor / balancing control via CAN commands (0x100)
#
# Victron DVCC / CCCM integration:
#   - charge_fet / discharge_fet reflect physical contactor state + fault latch
#   - protection flags driven from fault frames for Victron alarm display
#   - AllowToCharge / AllowToDischarge derived automatically by framework
#   - Current limits computed by framework CCCM tables (configured in config.default.ini):
#       CCCM_CV  : cell voltage derating (max cell voltage → CCL fraction)
#       CCCM_T   : cell temperature derating (sensors 1–4, feeds from max cell NTC)
#       CCCM_T_MOSFET: IC die temperature derating (sensor 0)
#   - Pack voltage = sum(24 logical cells) / 2  (module is 2P12S — two 12S halves in parallel)

from __future__ import absolute_import, division, print_function, unicode_literals
from battery import Battery, Cell
from utils import bytearray_to_string, logger
from struct import unpack
from time import time
import can
import sys


class Csbi_Can(Battery):

    BATTERYTYPE = "CSBI CAN"

    # -----------------------------------------------------------------------
    # CAN TX frame IDs (BMS → host)
    # -----------------------------------------------------------------------
    CAN_ID_STATUS     = 0x010   # BMS status frame
    CAN_ID_FAULT      = 0x020   # Per-fault detail frame
    CAN_ID_CCELL_BASE = 0x050   # C-channel cell voltages (0x050–0x055, 6 frames)
    CAN_ID_TEMPS_BASE = 0x450   # Temperature frames (0x450–0x453, 4 frames)
    CAN_ID_SM_ERRORS  = 0x550   # SM diagnostic bit-field (informational, not parsed)
    CAN_ID_SID_BASE   = 0x600   # Module serial IDs (not parsed)

    # Number of consecutive frames in each block
    CELL_VOLT_FRAMES  = 6       # 0x050–0x055 → 24 cells (4 per frame)
    TEMP_FRAMES       = 4       # 0x450–0x453 → 16 raw sensors (4 per frame)

    # -----------------------------------------------------------------------
    # CAN RX frame IDs (host → BMS)
    # -----------------------------------------------------------------------
    CAN_CMD_RX_ID        = 0x100  # Command frame sent to BMS
    CAN_CMD_TX_ID        = 0x101  # Acknowledgement from BMS

    # Command codes (byte 0 of command frame)
    CAN_CMD_CONTACTOR_EN = 0x01   # byte 1: 1=enable close, 0=open
    CAN_CMD_BALANCING_EN = 0x02   # byte 1: 1=enable, 0=disable

    # -----------------------------------------------------------------------
    # Fault type codes (byte 0 of fault frame 0x020)
    # -----------------------------------------------------------------------
    FAULT_UV            = 0x01   # undervoltage
    FAULT_OV            = 0x02   # overvoltage
    FAULT_UT            = 0x03   # undertemperature
    FAULT_OT            = 0x04   # overtemperature
    FAULT_VALIDATION    = 0x05   # data validation
    FAULT_PEC           = 0x06   # CRC / PEC error
    FAULT_SM_MUX        = 0x07   # SM mux test failure
    FAULT_SM_REF        = 0x08   # SM reference voltage failure
    FAULT_SM_SUPPLY     = 0x09   # SM supply voltage failure
    FAULT_SM_OPENWIRE   = 0x0A   # open-wire detection
    FAULT_SM_REDUNDANCY = 0x0B   # SM redundancy check failure

    # Seconds without a fault frame before the corresponding protection flag is cleared
    FAULT_CLEAR_DELAY   = 3.0

    def __init__(self, port, baud, address):
        super(Csbi_Can, self).__init__(port, baud, address)
        self.type = self.BATTERYTYPE
        self.cell_count = 0

        # BMS identification populated from the status frame
        self.module_type = None
        self.nr_modules  = None

        # Internal state mirrors of the status frame
        self._contactor_state  = False   # physical contactor closed
        self._fault_latched    = False   # UV/OV/OT/UT latch (cleared by BMS power-cycle)
        self._sm_fault_latched = False   # SM diagnostic fault latch

        # Fault age tracking for protection flag decay
        # key: (fault_type, index, module_idx)  value: last-seen timestamp
        self._fault_last_seen: dict = {}

        # Temporary cache for cell NTC temps from frame 0 (needed to compute max across frames 0+1)
        self._cell_temps_f0: list = []

        # Device address offset allows multiple BMS on one bus
        if address is not None and isinstance(address, (bytes, bytearray)):
            self.device_address = int.from_bytes(address, byteorder="big")
        else:
            self.device_address = 0

        self.history.exclude_values_to_calculate = ["charge_cycles", "total_ah_drawn"]

    # -----------------------------------------------------------------------
    # dbus-serialbattery public interface
    # -----------------------------------------------------------------------

    def connection_name(self) -> str:
        suffix = f"__{self.device_address}" if self.device_address != 0 else ""
        return f"CAN socketcan:{self.port}{suffix}"

    def unique_identifier(self) -> str:
        if self.address is not None and isinstance(self.address, (bytes, bytearray)):
            return self.port + "__" + bytearray_to_string(bytearray(self.address)).replace("\\", "0")
        return self.port

    def test_connection(self) -> bool:
        result = False
        try:
            result = self.get_settings()
            result = result and self.refresh_data()
        except Exception:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            if exc_tb:
                logger.error(
                    f"Exception in test_connection: {repr(exc_obj)} of type {exc_type} "
                    f"in {exc_tb.tb_frame.f_code.co_filename} line #{exc_tb.tb_lineno}"
                )
            else:
                logger.error(f"Exception in test_connection: {repr(exc_obj)} of type {exc_type}")
        return result

    def get_settings(self) -> bool:
        # All settings are populated dynamically from incoming CAN frames.
        return True

    def refresh_data(self) -> bool:
        return self._read_can_frames()

    # -----------------------------------------------------------------------
    # Main CAN frame dispatcher
    # -----------------------------------------------------------------------

    def _read_can_frames(self) -> bool:
        if not hasattr(self, "can_transport_interface") or self.can_transport_interface is None:
            logger.error("CSBI CAN: transport interface not available")
            return False

        cache_cb = getattr(self.can_transport_interface, "can_message_cache_callback", None)
        if cache_cb is None:
            logger.error("CSBI CAN: can_message_cache_callback not available")
            return False

        message_cache = cache_cb()
        if not isinstance(message_cache, dict):
            logger.error("CSBI CAN: invalid message cache format")
            return False

        # Bitmask to verify we received the minimum set of frames:
        #   bit 0 = at least one cell voltage frame
        #   bit 1 = status frame
        data_check = 0

        for frame_id, data in message_cache.items():
            arb_id = frame_id + self.device_address

            if arb_id == self.CAN_ID_STATUS and len(data) >= 8:
                self._parse_status(data)
                data_check |= 0x02

            elif arb_id == self.CAN_ID_FAULT and len(data) >= 7:
                self._parse_fault(data)

            elif self.CAN_ID_CCELL_BASE <= arb_id < self.CAN_ID_CCELL_BASE + self.CELL_VOLT_FRAMES:
                self._parse_cell_voltages(arb_id - self.CAN_ID_CCELL_BASE, data)
                data_check |= 0x01

            elif self.CAN_ID_TEMPS_BASE <= arb_id < self.CAN_ID_TEMPS_BASE + self.TEMP_FRAMES:
                self._parse_temperatures(arb_id - self.CAN_ID_TEMPS_BASE, data)

        self._decay_faults()

        if data_check == 0:
            logger.error("CSBI CAN: no frames received")
            return False

        # Charge/discharge permission: contactor must be closed and no fault latched
        healthy = self._contactor_state and not self._fault_latched and not self._sm_fault_latched
        self.charge_fet    = healthy
        self.discharge_fet = healthy

        if self.hardware_version is None and self.nr_modules is not None:
            self.hardware_version = f"CSBI CAN type=0x{self.module_type:02X} modules={self.nr_modules}"

        return True

    # -----------------------------------------------------------------------
    # Frame parsers
    # -----------------------------------------------------------------------

    def _parse_status(self, data: bytes) -> None:
        """
        Status frame 0x010 — 8 bytes:
          [0] contactor_state    1=closed 0=open
          [1] contactor_enable   master software enable flag
          [2] fault_latched      UV/OV/OT/UT latch (cleared only by BMS power-cycle)
          [3] balancing_status   1=balancing active
          [4] sm_fault_latched   SM diagnostic fault latch
          [5] reserved
          [6] module_type
          [7] nr_modules
        """
        self._contactor_state  = bool(data[0])
        self._fault_latched    = bool(data[2])
        self._sm_fault_latched = bool(data[4])
        self.balance_fet       = bool(data[3])
        self.module_type       = data[6]
        self.nr_modules        = data[7]

        for cell in self.cells:
            cell.balance = self.balance_fet

        if self._sm_fault_latched:
            self.protection.internal_failure = 2

    def _parse_fault(self, data: bytes) -> None:
        """
        Fault frame 0x020 — 8 bytes:
          [0] fault_type     see FAULT_* constants
          [1] index          cell or sensor index (0-based)
          [2] module_idx
          [3-4] value LE     measured value (mV or degC×10)
          [5-6] limit LE     limit that was exceeded
          [7] reserved
        """
        fault_type = data[0]
        self._fault_last_seen[(fault_type, data[1], data[2])] = time()

        if fault_type == self.FAULT_UV:
            self.protection.low_cell_voltage = 2
        elif fault_type == self.FAULT_OV:
            self.protection.high_cell_voltage = 2
        elif fault_type == self.FAULT_UT:
            self.protection.low_temperature       = 2
            self.protection.low_charge_temperature = 2
        elif fault_type == self.FAULT_OT:
            self.protection.high_temperature        = 2
            self.protection.high_charge_temperature = 2
        elif fault_type in (
            self.FAULT_VALIDATION, self.FAULT_PEC,
            self.FAULT_SM_MUX, self.FAULT_SM_REF, self.FAULT_SM_SUPPLY,
            self.FAULT_SM_OPENWIRE, self.FAULT_SM_REDUNDANCY,
        ):
            self.protection.internal_failure = 2

    def _decay_faults(self) -> None:
        """Clear protection flags for any fault type not seen within FAULT_CLEAR_DELAY seconds."""
        now = time()
        active = {k[0] for k, t in self._fault_last_seen.items() if now - t < self.FAULT_CLEAR_DELAY}

        if self.FAULT_UV not in active:
            self.protection.low_cell_voltage = 0
        if self.FAULT_OV not in active:
            self.protection.high_cell_voltage = 0
        if self.FAULT_UT not in active:
            self.protection.low_temperature       = 0
            self.protection.low_charge_temperature = 0
        if self.FAULT_OT not in active:
            self.protection.high_temperature        = 0
            self.protection.high_charge_temperature = 0

        hw_faults = {
            self.FAULT_VALIDATION, self.FAULT_PEC,
            self.FAULT_SM_MUX, self.FAULT_SM_REF, self.FAULT_SM_SUPPLY,
            self.FAULT_SM_OPENWIRE, self.FAULT_SM_REDUNDANCY,
        }
        if not (active & hw_faults) and not self._sm_fault_latched:
            self.protection.internal_failure = 0

    def _parse_cell_voltages(self, frame_index: int, data: bytes) -> None:
        """
        Cell voltage frames 0x050–0x055 — 8 bytes each.
        4 cells per frame as 16-bit LE in mV.
        Frame 0 → cells 0–3, frame 1 → cells 4–7, …, frame 5 → cells 20–23.

        The module is 2P12S (two 12S half-modules in parallel), so pack voltage
        equals the sum of the 24 logical cell voltages divided by 2.
        """
        cell_offset = frame_index * 4
        for i in range(4):
            byte_offset = i * 2
            if byte_offset + 2 > len(data):
                break
            raw = unpack("<H", data[byte_offset:byte_offset + 2])[0]
            voltage = raw * 0.001  # mV → V
            if voltage <= 0:
                continue
            cell_index = cell_offset + i
            while len(self.cells) <= cell_index:
                self.cells.append(Cell(False))
            self.cells[cell_index].voltage = voltage

        self.cell_count = len(self.cells)
        self.voltage    = self.get_cell_voltage_sum() / 2

    def _parse_temperatures(self, frame_index: int, data: bytes) -> None:
        """
        Temperature frames 0x450–0x453 — 8 bytes each.
        4 sensors per frame as 16-bit signed LE in degC×10.

        dbus-serialbattery exposes only 5 temperature slots (sensors 0–4).
        Mapping chosen to maximise CCCM coverage:
          sensor 0 (temperature_mos) = IC die temp   → feeds CCCM_T_MOSFET (derating starts 70°C)
          sensor 1 (temperature_1)   = max cell NTC  → feeds CCCM_T (worst-case cell temp)
          sensor 2 (temperature_2)   = first cell NTC (representative cell temp)
          sensor 3 (temperature_3)   = PCB NTC 1
          sensor 4 (temperature_4)   = PCB NTC 2

        Frame layout:
          0x450 (frame 0): cell NTC 1–4
          0x451 (frame 1): cell NTC 5–8
          0x452 (frame 2): PCB NTC 1–4
          0x453 (frame 3): PCB NTC 5–6, IC die 1–2
        """
        temps = []
        for i in range(4):
            if i * 2 + 2 > len(data):
                break
            raw = unpack("<h", data[i * 2:i * 2 + 2])[0]
            temps.append(raw * 0.1 if raw != 0 else None)

        valid = [t for t in temps if t is not None and -40 <= t <= 100]

        if frame_index == 0:
            self._cell_temps_f0 = valid
            if valid:
                self.to_temperature(2, valid[0])     # first cell NTC → sensor 2

        elif frame_index == 1:
            all_cell = self._cell_temps_f0 + valid
            if all_cell:
                self.to_temperature(1, max(all_cell))  # max cell NTC → sensor 1

        elif frame_index == 2:
            if len(valid) >= 1:
                self.to_temperature(3, valid[0])
            if len(valid) >= 2:
                self.to_temperature(4, valid[1])

        elif frame_index == 3:
            # IC die temps are in the second pair (indices 2–3); valid up to 100°C (clamped by to_temperature)
            ic_die = [t for t in temps[2:] if t is not None and -40 <= t <= 100]
            if ic_die:
                self.to_temperature(0, max(ic_die))  # IC die → sensor 0 (MOSFET proxy)

    # -----------------------------------------------------------------------
    # Contactor / balancing control (host → BMS via CAN command)
    # -----------------------------------------------------------------------

    def _send_can_command(self, cmd: int, value: int) -> bool:
        """Send a 2-byte command frame to the BMS on CAN_CMD_RX_ID (0x100)."""
        try:
            bus = getattr(self.can_transport_interface, "can_bus", None)
            if bus is None:
                logger.warning("CSBI CAN: cannot send command — can_bus not available")
                return False
            msg = can.Message(
                arbitration_id=self.CAN_CMD_RX_ID + self.device_address,
                data=[cmd, value],
                is_extended_id=False,
            )
            bus.send(msg)
            return True
        except Exception as e:
            logger.error(f"CSBI CAN: error sending command 0x{cmd:02X}: {e}")
            return False

    def force_charging_off_callback(self, path: str, value) -> bool:
        """Victron 'Force charging off' button — opens/closes the BMS contactor."""
        enable = 0 if value else 1
        return self._send_can_command(self.CAN_CMD_CONTACTOR_EN, enable)

    def force_discharging_off_callback(self, path: str, value) -> bool:
        """Victron 'Force discharging off' button — opens/closes the BMS contactor."""
        enable = 0 if value else 1
        return self._send_can_command(self.CAN_CMD_CONTACTOR_EN, enable)

    def turn_balancing_off_callback(self, path: str, value) -> bool:
        """Victron balancing toggle."""
        enable = 0 if value else 1
        return self._send_can_command(self.CAN_CMD_BALANCING_EN, enable)
