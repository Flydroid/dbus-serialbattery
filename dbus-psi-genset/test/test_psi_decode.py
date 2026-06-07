# -*- coding: utf-8 -*-
"""Unit tests for the pure PSI decoding helpers (no hardware needed)."""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

import psi  # noqa: E402


def test_decode_standby():
    d = psi.decode_status(0x0000)
    assert d["working"] is False
    assert d["error"] is False
    assert d["faults"] == []
    assert d["load_level"] == "light"
    assert d["dc_input"] == "ok"
    assert psi.status_code(d) == psi.STATUS_STANDBY


def test_decode_working():
    d = psi.decode_status(0x0001)  # bit0 set
    assert d["working"] is True
    assert psi.status_code(d) == psi.STATUS_RUNNING


def test_decode_error_takes_priority():
    # bit0 (working) and bit1 (error) both set -> Error wins
    d = psi.decode_status(0x0003)
    assert d["error"] is True
    assert psi.status_code(d) == psi.STATUS_ERROR


def test_decode_fault_bits():
    # bit7 input over-current + bit11 short circuit
    word = (1 << 7) | (1 << 11)
    d = psi.decode_status(word)
    assert "input over-current" in d["faults"]
    assert "short circuit" in d["faults"]


def test_decode_load_and_dc_input_fields():
    # load level bits 13-12 = 11 (overload), dc input bits 15-14 = 01 (LVD)
    word = (0b11 << 12) | (0b01 << 14)
    d = psi.decode_status(word)
    assert d["load_level"] == "overload"
    assert d["dc_input"] == "LVD"


def test_error_text_includes_over_temp():
    d = psi.decode_status((1 << 10))  # no output
    d["over_temp_inverter"] = True
    d["over_temp_mosfet"] = False
    text = psi.error_text(d)
    assert "no output" in text
    assert "inverter over-temperature" in text
    assert "MOSFET" not in text


def test_error_text_empty_when_clear():
    assert psi.error_text(psi.decode_status(0x0001)) == ""


def test_clamp_threshold_ranges():
    assert psi.clamp_threshold("LVD", 9.0) == 10.3   # below min
    assert psi.clamp_threshold("LVD", 12.0) == 11.3  # above max
    assert psi.clamp_threshold("LVD", 10.8) == 10.8  # in range
    assert psi.clamp_threshold("HVD", 99.0) == 15.0


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
