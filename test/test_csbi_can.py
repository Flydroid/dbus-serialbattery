# -*- coding: utf-8 -*-
"""
Unit tests for csbi_can.py

Run with:
    cd e:/Git/dbus-serialbattery
    .venv/Scripts/python -m pytest test/test_csbi_can.py -v
"""

import sys
import os
import struct
from time import time
from unittest.mock import MagicMock, patch, call

import pytest

# Make the dbus-serialbattery package importable without an installed Victron environment
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dbus-serialbattery"))

# Stub modules that are only available on a Victron GX device
for mod in ["dbus", "gi", "gi.repository", "gi.repository.GLib"]:
    sys.modules.setdefault(mod, MagicMock())

from bms.csbi_can import Csbi_Can  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_bms(address=None):
    """Create a Csbi_Can instance with a mocked CAN transport."""
    bms = Csbi_Can(port="can0", baud=500000, address=address)
    transport = MagicMock()
    transport.can_bus = MagicMock()
    bms.set_can_transport_interface(transport)
    return bms


def set_cache(bms, frames: dict):
    """Inject a frame dict into the mock transport cache callback."""
    bms.can_transport_interface.can_message_cache_callback.return_value = frames


def make_cell_volt_frame(voltages_mv: list) -> bytes:
    """Pack up to 4 cell voltages (mV as int) into an 8-byte frame."""
    data = bytearray(8)
    for i, mv in enumerate(voltages_mv[:4]):
        struct.pack_into("<H", data, i * 2, mv)
    return bytes(data)


def make_temp_frame(temps_deci_c: list) -> bytes:
    """Pack up to 4 temperatures (degC × 10 as int, signed) into an 8-byte frame."""
    data = bytearray(8)
    for i, t in enumerate(temps_deci_c[:4]):
        struct.pack_into("<h", data, i * 2, t)
    return bytes(data)


def make_status_frame(contactor=1, contactor_enable=1, fault_latched=0,
                      balancing=0, sm_fault=0, module_type=0x01, nr_modules=1) -> bytes:
    return bytes([contactor, contactor_enable, fault_latched, balancing,
                  sm_fault, 0, module_type, nr_modules])


def make_fault_frame(fault_type, index=0, module_idx=0, value=0, limit=0) -> bytes:
    data = bytearray(8)
    data[0] = fault_type
    data[1] = index
    data[2] = module_idx
    struct.pack_into("<H", data, 3, value)
    struct.pack_into("<H", data, 5, limit)
    return bytes(data)


# Minimal cache that satisfies data_check (status + one voltage frame)
def minimal_cache(bms, extra: dict = None):
    frames = {
        Csbi_Can.CAN_ID_STATUS:     make_status_frame(),
        Csbi_Can.CAN_ID_CCELL_BASE: make_cell_volt_frame([3300, 3310, 3320, 3330]),
    }
    if extra:
        frames.update(extra)
    set_cache(bms, frames)


# ---------------------------------------------------------------------------
# Transport / connection
# ---------------------------------------------------------------------------

class TestConnection:
    def test_no_transport_returns_false(self):
        bms = Csbi_Can(port="can0", baud=500000, address=None)
        assert bms.refresh_data() is False

    def test_none_transport_returns_false(self):
        bms = Csbi_Can(port="can0", baud=500000, address=None)
        bms.can_transport_interface = None
        assert bms.refresh_data() is False

    def test_no_callback_returns_false(self):
        bms = make_bms()
        del bms.can_transport_interface.can_message_cache_callback
        assert bms.refresh_data() is False

    def test_non_dict_cache_returns_false(self):
        bms = make_bms()
        bms.can_transport_interface.can_message_cache_callback.return_value = []
        assert bms.refresh_data() is False

    def test_empty_cache_returns_false(self):
        bms = make_bms()
        set_cache(bms, {})
        assert bms.refresh_data() is False

    def test_voltage_only_cache_returns_true(self):
        """data_check only needs bit 0 (voltage) OR bit 1 (status) to be set."""
        bms = make_bms()
        set_cache(bms, {Csbi_Can.CAN_ID_CCELL_BASE: make_cell_volt_frame([3300, 3300, 3300, 3300])})
        assert bms.refresh_data() is True


# ---------------------------------------------------------------------------
# Status frame
# ---------------------------------------------------------------------------

class TestStatusFrame:
    def test_contactor_closed_healthy(self):
        bms = make_bms()
        minimal_cache(bms)
        bms.refresh_data()
        assert bms.charge_fet is True
        assert bms.discharge_fet is True

    def test_contactor_open_gates_fets(self):
        bms = make_bms()
        set_cache(bms, {
            Csbi_Can.CAN_ID_STATUS:     make_status_frame(contactor=0),
            Csbi_Can.CAN_ID_CCELL_BASE: make_cell_volt_frame([3300, 3300, 3300, 3300]),
        })
        bms.refresh_data()
        assert bms.charge_fet is False
        assert bms.discharge_fet is False

    def test_fault_latched_gates_fets(self):
        bms = make_bms()
        set_cache(bms, {
            Csbi_Can.CAN_ID_STATUS:     make_status_frame(contactor=1, fault_latched=1),
            Csbi_Can.CAN_ID_CCELL_BASE: make_cell_volt_frame([3300, 3300, 3300, 3300]),
        })
        bms.refresh_data()
        assert bms.charge_fet is False
        assert bms.discharge_fet is False

    def test_sm_fault_gates_fets(self):
        bms = make_bms()
        set_cache(bms, {
            Csbi_Can.CAN_ID_STATUS:     make_status_frame(contactor=1, sm_fault=1),
            Csbi_Can.CAN_ID_CCELL_BASE: make_cell_volt_frame([3300, 3300, 3300, 3300]),
        })
        bms.refresh_data()
        assert bms.charge_fet is False
        assert bms.discharge_fet is False

    def test_sm_fault_sets_internal_failure_alarm(self):
        bms = make_bms()
        set_cache(bms, {
            Csbi_Can.CAN_ID_STATUS:     make_status_frame(sm_fault=1),
            Csbi_Can.CAN_ID_CCELL_BASE: make_cell_volt_frame([3300, 3300, 3300, 3300]),
        })
        bms.refresh_data()
        assert bms.protection.internal_failure == 2

    def test_balancing_propagated_to_cells(self):
        bms = make_bms()
        # First populate cells
        set_cache(bms, {
            Csbi_Can.CAN_ID_CCELL_BASE: make_cell_volt_frame([3300, 3310, 3320, 3330]),
        })
        bms.refresh_data()
        # Now set status with balancing on
        set_cache(bms, {
            Csbi_Can.CAN_ID_STATUS:     make_status_frame(balancing=1),
            Csbi_Can.CAN_ID_CCELL_BASE: make_cell_volt_frame([3300, 3310, 3320, 3330]),
        })
        bms.refresh_data()
        assert bms.balance_fet is True
        assert all(c.balance for c in bms.cells)

    def test_module_info_sets_hardware_version(self):
        bms = make_bms()
        minimal_cache(bms)
        bms.refresh_data()
        assert bms.hardware_version is not None
        assert "0x01" in bms.hardware_version

    def test_hardware_version_not_overwritten_on_second_call(self):
        bms = make_bms()
        minimal_cache(bms)
        bms.refresh_data()
        first = bms.hardware_version
        bms.refresh_data()
        assert bms.hardware_version == first


# ---------------------------------------------------------------------------
# Fault frame → protection flags
# ---------------------------------------------------------------------------

class TestFaultFrame:
    def _refresh_with_fault(self, fault_type):
        bms = make_bms()
        set_cache(bms, {
            Csbi_Can.CAN_ID_STATUS:     make_status_frame(),
            Csbi_Can.CAN_ID_CCELL_BASE: make_cell_volt_frame([3300, 3300, 3300, 3300]),
            Csbi_Can.CAN_ID_FAULT:      make_fault_frame(fault_type),
        })
        bms.refresh_data()
        return bms

    def test_uv_sets_low_cell_voltage(self):
        bms = self._refresh_with_fault(Csbi_Can.FAULT_UV)
        assert bms.protection.low_cell_voltage == 2

    def test_ov_sets_high_cell_voltage(self):
        bms = self._refresh_with_fault(Csbi_Can.FAULT_OV)
        assert bms.protection.high_cell_voltage == 2

    def test_ut_sets_low_temperature_flags(self):
        bms = self._refresh_with_fault(Csbi_Can.FAULT_UT)
        assert bms.protection.low_temperature == 2
        assert bms.protection.low_charge_temperature == 2

    def test_ot_sets_high_temperature_flags(self):
        bms = self._refresh_with_fault(Csbi_Can.FAULT_OT)
        assert bms.protection.high_temperature == 2
        assert bms.protection.high_charge_temperature == 2

    @pytest.mark.parametrize("fault_type", [
        Csbi_Can.FAULT_VALIDATION,
        Csbi_Can.FAULT_PEC,
        Csbi_Can.FAULT_SM_MUX,
        Csbi_Can.FAULT_SM_REF,
        Csbi_Can.FAULT_SM_SUPPLY,
        Csbi_Can.FAULT_SM_OPENWIRE,
        Csbi_Can.FAULT_SM_REDUNDANCY,
    ])
    def test_hw_faults_set_internal_failure(self, fault_type):
        bms = self._refresh_with_fault(fault_type)
        assert bms.protection.internal_failure == 2

    def test_fault_decay_clears_flag_after_delay(self):
        bms = make_bms()
        # Inject a fault, aged beyond the clear delay
        past = time() - Csbi_Can.FAULT_CLEAR_DELAY - 1.0
        bms._fault_last_seen[(Csbi_Can.FAULT_UV, 0, 0)] = past
        bms.protection.low_cell_voltage = 2

        set_cache(bms, {
            Csbi_Can.CAN_ID_STATUS:     make_status_frame(),
            Csbi_Can.CAN_ID_CCELL_BASE: make_cell_volt_frame([3300, 3300, 3300, 3300]),
            # No fault frame this cycle
        })
        bms.refresh_data()
        assert bms.protection.low_cell_voltage == 0

    def test_fault_decay_does_not_clear_sm_fault_while_latched(self):
        bms = make_bms()
        bms._sm_fault_latched = True
        bms.protection.internal_failure = 2

        set_cache(bms, {
            Csbi_Can.CAN_ID_STATUS:     make_status_frame(sm_fault=1),
            Csbi_Can.CAN_ID_CCELL_BASE: make_cell_volt_frame([3300, 3300, 3300, 3300]),
        })
        bms.refresh_data()
        assert bms.protection.internal_failure == 2

    def test_recent_fault_not_cleared(self):
        bms = make_bms()
        set_cache(bms, {
            Csbi_Can.CAN_ID_STATUS:     make_status_frame(),
            Csbi_Can.CAN_ID_CCELL_BASE: make_cell_volt_frame([3300, 3300, 3300, 3300]),
            Csbi_Can.CAN_ID_FAULT:      make_fault_frame(Csbi_Can.FAULT_OV),
        })
        bms.refresh_data()
        assert bms.protection.high_cell_voltage == 2


# ---------------------------------------------------------------------------
# Cell voltage frames
# ---------------------------------------------------------------------------

class TestCellVoltageFrames:
    def test_frame0_populates_cells_0_to_3(self):
        bms = make_bms()
        voltages_mv = [3300, 3310, 3320, 3330]
        set_cache(bms, {Csbi_Can.CAN_ID_CCELL_BASE: make_cell_volt_frame(voltages_mv)})
        bms.refresh_data()
        for i, mv in enumerate(voltages_mv):
            assert abs(bms.cells[i].voltage - mv * 0.001) < 1e-6

    def test_all_6_frames_populate_24_cells(self):
        bms = make_bms()
        frames = {}
        for fi in range(6):
            frames[Csbi_Can.CAN_ID_CCELL_BASE + fi] = make_cell_volt_frame([3300 + fi * 10] * 4)
        set_cache(bms, frames)
        bms.refresh_data()
        assert bms.cell_count == 24

    def test_pack_voltage_is_sum_divided_by_2(self):
        bms = make_bms()
        frames = {}
        for fi in range(6):
            frames[Csbi_Can.CAN_ID_CCELL_BASE + fi] = make_cell_volt_frame([3400] * 4)
        set_cache(bms, frames)
        bms.refresh_data()
        expected = 24 * 3.400 / 2
        assert abs(bms.voltage - expected) < 0.01

    def test_zero_voltage_cells_skipped(self):
        bms = make_bms()
        set_cache(bms, {Csbi_Can.CAN_ID_CCELL_BASE: make_cell_volt_frame([0, 3300, 0, 3320])})
        bms.refresh_data()
        # Cells at indices 1 and 3 should have voltages; 0 and 2 either absent or zero
        assert bms.cells[1].voltage == pytest.approx(3.300, abs=1e-4)
        assert bms.cells[3].voltage == pytest.approx(3.320, abs=1e-4)

    def test_device_address_offset_applied_to_voltage_frames(self):
        bms = make_bms(address=b"\x10")  # device_address = 16
        # Frame IDs arriving on bus are offset by -device_address
        raw_id = Csbi_Can.CAN_ID_CCELL_BASE - 16
        set_cache(bms, {raw_id: make_cell_volt_frame([3300, 3310, 3320, 3330])})
        bms.refresh_data()
        assert len(bms.cells) == 4


# ---------------------------------------------------------------------------
# Temperature frames
# ---------------------------------------------------------------------------

class TestTemperatureFrames:
    def test_frame0_sets_sensor_2(self):
        bms = make_bms()
        minimal_cache(bms, {Csbi_Can.CAN_ID_TEMPS_BASE: make_temp_frame([250, 260, 270, 280])})
        bms.refresh_data()
        assert bms.temperature_2 == pytest.approx(25.0, abs=0.1)

    def test_frame1_sets_sensor_1_as_max(self):
        bms = make_bms()
        # frame 0: 20°C, 22°C, 24°C, 26°C
        # frame 1: 28°C, 30°C, 32°C, 34°C
        # max overall = 34°C → sensor 1
        frames = {
            Csbi_Can.CAN_ID_CCELL_BASE:     make_cell_volt_frame([3300, 3300, 3300, 3300]),
            Csbi_Can.CAN_ID_TEMPS_BASE:     make_temp_frame([200, 220, 240, 260]),   # 20..26°C
            Csbi_Can.CAN_ID_TEMPS_BASE + 1: make_temp_frame([280, 300, 320, 340]),   # 28..34°C
        }
        set_cache(bms, frames)
        bms.refresh_data()
        assert bms.temperature_1 == pytest.approx(34.0, abs=0.1)

    def test_frame2_sets_pcb_sensors_3_and_4(self):
        bms = make_bms()
        minimal_cache(bms, {Csbi_Can.CAN_ID_TEMPS_BASE + 2: make_temp_frame([350, 360, 370, 380])})
        bms.refresh_data()
        assert bms.temperature_3 == pytest.approx(35.0, abs=0.1)
        assert bms.temperature_4 == pytest.approx(36.0, abs=0.1)

    def test_frame3_ic_die_sets_sensor_0(self):
        bms = make_bms()
        # bytes [4:8] of frame 3 carry IC die temps (indices 2–3 in the 4-sensor array)
        # 0, 0 at indices 0–1 (PCB NTC 5–6 placeholder), 75.0°C and 80.0°C for IC die
        minimal_cache(bms, {Csbi_Can.CAN_ID_TEMPS_BASE + 3: make_temp_frame([0, 0, 750, 800])})
        bms.refresh_data()
        assert bms.temperature_mos == pytest.approx(80.0, abs=0.1)

    def test_temperature_zero_values_ignored(self):
        bms = make_bms()
        minimal_cache(bms, {Csbi_Can.CAN_ID_TEMPS_BASE: make_temp_frame([0, 0, 0, 250])})
        bms.refresh_data()
        assert bms.temperature_2 == pytest.approx(25.0, abs=0.1)

    def test_temperature_out_of_range_ignored(self):
        bms = make_bms()
        # -50°C is below the -40°C valid floor
        minimal_cache(bms, {Csbi_Can.CAN_ID_TEMPS_BASE: make_temp_frame([-500, 250, 0, 0])})
        bms.refresh_data()
        # Sensor 2 should be set from the second value (25°C), not the invalid first
        assert bms.temperature_2 == pytest.approx(25.0, abs=0.1)


# ---------------------------------------------------------------------------
# CAN command TX
# ---------------------------------------------------------------------------

class TestCanCommands:
    def test_send_can_command_sends_correct_frame(self):
        bms = make_bms()
        result = bms._send_can_command(Csbi_Can.CAN_CMD_CONTACTOR_EN, 1)
        assert result is True
        sent = bms.can_transport_interface.can_bus.send.call_args[0][0]
        assert sent.arbitration_id == Csbi_Can.CAN_CMD_RX_ID
        assert list(sent.data) == [Csbi_Can.CAN_CMD_CONTACTOR_EN, 1]
        assert sent.is_extended_id is False

    def test_send_can_command_no_bus_returns_false(self):
        bms = make_bms()
        bms.can_transport_interface.can_bus = None
        assert bms._send_can_command(Csbi_Can.CAN_CMD_CONTACTOR_EN, 1) is False

    def test_send_can_command_device_address_offset(self):
        bms = make_bms(address=b"\x05")
        bms._send_can_command(Csbi_Can.CAN_CMD_CONTACTOR_EN, 1)
        sent = bms.can_transport_interface.can_bus.send.call_args[0][0]
        assert sent.arbitration_id == Csbi_Can.CAN_CMD_RX_ID + 5

    def test_force_charging_off_sends_contactor_disable(self):
        bms = make_bms()
        bms.force_charging_off_callback("/path", True)  # value=True → "force off" → enable=0
        sent = bms.can_transport_interface.can_bus.send.call_args[0][0]
        assert list(sent.data) == [Csbi_Can.CAN_CMD_CONTACTOR_EN, 0]

    def test_force_charging_on_sends_contactor_enable(self):
        bms = make_bms()
        bms.force_charging_off_callback("/path", False)  # value=False → "release" → enable=1
        sent = bms.can_transport_interface.can_bus.send.call_args[0][0]
        assert list(sent.data) == [Csbi_Can.CAN_CMD_CONTACTOR_EN, 1]

    def test_force_discharging_off_sends_contactor_disable(self):
        bms = make_bms()
        bms.force_discharging_off_callback("/path", True)
        sent = bms.can_transport_interface.can_bus.send.call_args[0][0]
        assert list(sent.data) == [Csbi_Can.CAN_CMD_CONTACTOR_EN, 0]

    def test_turn_balancing_off_sends_balancing_disable(self):
        bms = make_bms()
        bms.turn_balancing_off_callback("/path", True)  # value=True → "turn off" → enable=0
        sent = bms.can_transport_interface.can_bus.send.call_args[0][0]
        assert list(sent.data) == [Csbi_Can.CAN_CMD_BALANCING_EN, 0]

    def test_turn_balancing_on_sends_balancing_enable(self):
        bms = make_bms()
        bms.turn_balancing_off_callback("/path", False)  # value=False → "release" → enable=1
        sent = bms.can_transport_interface.can_bus.send.call_args[0][0]
        assert list(sent.data) == [Csbi_Can.CAN_CMD_BALANCING_EN, 1]

    def test_send_exception_returns_false(self):
        bms = make_bms()
        bms.can_transport_interface.can_bus.send.side_effect = Exception("bus error")
        assert bms._send_can_command(Csbi_Can.CAN_CMD_CONTACTOR_EN, 1) is False


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

class TestMisc:
    def test_connection_name_no_address(self):
        bms = Csbi_Can(port="can0", baud=500000, address=None)
        assert bms.connection_name() == "CAN socketcan:can0"

    def test_connection_name_with_address(self):
        bms = Csbi_Can(port="can0", baud=500000, address=b"\x02")
        assert bms.connection_name() == "CAN socketcan:can0__2"

    def test_unique_identifier_no_address(self):
        bms = Csbi_Can(port="can0", baud=500000, address=None)
        assert bms.unique_identifier() == "can0"

    def test_get_settings_returns_true(self):
        bms = Csbi_Can(port="can0", baud=500000, address=None)
        assert bms.get_settings() is True
