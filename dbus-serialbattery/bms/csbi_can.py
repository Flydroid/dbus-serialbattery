# -*- coding: utf-8 -*-

# NOTES
# CSBI CAN BMS implementation
# Based on proven frame parsing from monitor_csbi_live.py
# Supports Module1 cell voltages, cell temperatures, PCB temperatures, and IC temperatures
# Uses CSBI CAN protocol specification from csbi_can.json

from __future__ import absolute_import, division, print_function, unicode_literals
from battery import Battery, Cell
from utils import bytearray_to_string, logger
from struct import unpack_from, unpack
from time import sleep, time
from typing import Any, Dict
import sys


class Csbi_Can(Battery):
    def __init__(self, port, baud, address):
        super(Csbi_Can, self).__init__(port, baud, address)
        self.cell_count = 0
        self.type = self.BATTERYTYPE
        self.history.exclude_values_to_calculate = ["charge_cycles", "total_ah_drawn"]

        # If multiple BMS are used simultaneously, the device address can be set
        # (default address is 0) to change the CAN frame ID sent by the BMS
        self.device_address = int.from_bytes(address, byteorder="big") if address is not None and isinstance(address, (bytes, bytearray)) else 0
        self.last_error_time = 0
        self.error_active = False

    BATTERYTYPE = "CSBI CAN"

    # CSBI CAN frame types based on csbi_can.json
    CELL_VOLT_0 = "CELL_VOLT_0"
    CELL_VOLT_1 = "CELL_VOLT_1"
    CELL_VOLT_2 = "CELL_VOLT_2"
    CELL_VOLT_3 = "CELL_VOLT_3"
    CELL_VOLT_4 = "CELL_VOLT_4"
    CELL_VOLT_5 = "CELL_VOLT_5"
    CELL_TEMP_0 = "CELL_TEMP_0"
    CELL_TEMP_1 = "CELL_TEMP_1"
    PCB_TEMP_0 = "PCB_TEMP_0"
    PCB_TEMP_1 = "PCB_TEMP_1"

    # CSBI CAN frame IDs from csbi_can.json (Module1 only)
    CAN_FRAMES = {
        CELL_VOLT_0: [80],      # C_Channel_Cell_Voltages_0: Module1_C_Cell1-4
        CELL_VOLT_1: [81],      # C_Channel_Cell_Voltages_1: Module1_C_Cell5-8
        CELL_VOLT_2: [82],      # C_Channel_Cell_Voltages_2: Module1_C_Cell9-12
        CELL_VOLT_3: [83],      # C_Channel_Cell_Voltages_3: Module1_C_Cell13-16
        CELL_VOLT_4: [84],      # C_Channel_Cell_Voltages_4: Module1_C_Cell17-20
        CELL_VOLT_5: [85],      # C_Channel_Cell_Voltages_5: Module1_C_Cell21-24
        CELL_TEMP_0: [1104],    # Temperatures_0: Module1_Cell_Temp_1-4
        CELL_TEMP_1: [1105],    # Temperatures_1: Module1_Cell_Temp_5-8
        PCB_TEMP_0: [1106],     # Temperatures_2: Module1_PCB_Temp_1-4
        PCB_TEMP_1: [1107],     # Temperatures_3: Module1_PCB_Temp_5-6, IC_Temp_1-2
    }

    def connection_name(self) -> str:
        return f"CAN socketcan:{self.port}" + (f"__{self.device_address}" if self.device_address != 0 else "")

    def unique_identifier(self) -> str:
        """
        Used to identify a BMS when multiple BMS are connected
        Provide a unique identifier from the BMS to identify a BMS, if multiple same BMS are connected
        """
        if self.address is not None and isinstance(self.address, bytearray):
            return self.port + "__" + bytearray_to_string(self.address).replace("\\", "0")
        elif self.address is not None and isinstance(self.address, bytes):
            return self.port + "__" + bytearray_to_string(bytearray(self.address)).replace("\\", "0")
        else:
            return self.port

    def test_connection(self):
        """
        Test connection to the CSBI CAN BMS
        Return True if success, False for failure
        """
        result = False
        try:
            # get settings to check if the data is valid and the connection is working
            result = self.get_settings()

            # get the rest of the data to be sure, that all data is valid and the correct battery type is recognized
            # only read next data if the first one was successful, this saves time when checking multiple battery types
            result = result and self.refresh_data()
        except Exception:
            (
                exception_type,
                exception_object,
                exception_traceback,
            ) = sys.exc_info()
            if exception_traceback is not None:
                file = exception_traceback.tb_frame.f_code.co_filename
                line = exception_traceback.tb_lineno
                logger.error(f"Exception occurred: {repr(exception_object)} of type {exception_type} in {file} line #{line}")
            else:
                logger.error(f"Exception occurred: {repr(exception_object)} of type {exception_type}")
            result = False

        return result

    def get_settings(self):
        """
        After successful connection get_settings() will be called to set up the battery
        Set the current limits, populate cell count, etc
        Return True if success, False for failure
        """
        return True

    def refresh_data(self):
        """
        Call all functions that will refresh the battery data.
        This will be called for every iteration (1 second)
        Return True if success, False for failure
        """
        result = self.read_csbi_can()
        # check if connection success
        if result is False:
            return False

        return True

    def update_cell_voltages_from_frame(self, frame_type, data):
        """
        Update cell voltages from CSBI CAN data based on frame type
        Each frame contains 4 cells as 16-bit values with 0.001V scaling
        """
        if len(data) < 8:
            return
            
        # Determine starting cell index based on frame type
        cell_offset = 0
        if frame_type == self.CELL_VOLT_0:
            cell_offset = 0   # Cells 1-4
        elif frame_type == self.CELL_VOLT_1:
            cell_offset = 4   # Cells 5-8
        elif frame_type == self.CELL_VOLT_2:
            cell_offset = 8   # Cells 9-12
        elif frame_type == self.CELL_VOLT_3:
            cell_offset = 12  # Cells 13-16
        elif frame_type == self.CELL_VOLT_4:
            cell_offset = 16  # Cells 17-20
        elif frame_type == self.CELL_VOLT_5:
            cell_offset = 20  # Cells 21-24
        else:
            return
            
        # Parse 4 cells from this frame (16-bit little endian, 0.001V scaling)
        for i in range(4):
            cell_index = cell_offset + i
            byte_offset = i * 2
            
            if byte_offset + 1 < len(data):
                # Unpack 16-bit little endian value (same as monitor script)
                cell_voltage_raw = unpack("<H", data[byte_offset:byte_offset + 2])[0]
                cell_voltage = cell_voltage_raw * 0.001  # Convert to volts
                
                if cell_voltage > 0:  # Only update if voltage is valid
                    # Ensure we have enough cells
                    while len(self.cells) <= cell_index:
                        self.cells.append(Cell(False))
                    
                    self.cells[cell_index].voltage = cell_voltage
                    
        # Update cell count and total voltage
        self.cell_count = len(self.cells)
        self.voltage = self.get_cell_voltage_sum()/2 # the module is made up of 2 halfmodules, so we divide the total voltage by 2

    def update_temperatures_from_frame(self, frame_type, data):
        """
        Update temperatures from CSBI CAN data based on frame type
        Uses the same parsing logic as monitor_csbi_live.py
        Each frame contains 4 temperature sensors as 16-bit signed values with 0.1°C scaling
        """
        if len(data) < 8:
            return
            
        # Parse temperature data according to CSBI specification:
        # - 16-bit signed little-endian values  
        # - Scaling factor: 0.1 (temps are in tenths of degrees)
        
        for i in range(4):  # 4 temperature sensors per frame
            if len(data) >= (i * 2 + 2):
                # Parse 16-bit signed little-endian value (same as monitor script)
                temp_raw = unpack("<h", data[i*2:i*2+2])[0]  # <h for signed 16-bit
                
                if temp_raw != 0:  # Skip zero values (likely invalid)
                    # Apply CSBI scaling: 0.1 degrees per unit
                    temp_celsius = temp_raw * 0.1
                    
                    # Store if temperature is reasonable (-40°C to 85°C)
                    if -40 <= temp_celsius <= 85:
                        # Determine sensor index based on frame type
                        if frame_type == self.CELL_TEMP_0:
                            # Cell temperatures 1-4
                            sensor_index = i + 1
                            self.to_temperature(sensor_index, temp_celsius)
                        elif frame_type == self.CELL_TEMP_1:
                            # Cell temperatures 5-8
                            sensor_index = i + 5
                            self.to_temperature(sensor_index, temp_celsius)
                        elif frame_type == self.PCB_TEMP_0:
                            # PCB temperatures 1-4 - store as additional temp sensors
                            sensor_index = i + 9  # Offset after 8 cell temps
                            self.to_temperature(sensor_index, temp_celsius)
                        elif frame_type == self.PCB_TEMP_1:
                            # PCB temperatures 5-6 + IC temperatures 1-2
                            if i < 2:
                                # PCB temps 5-6
                                sensor_index = i + 13  # Offset after 8 cell + 4 PCB temps
                                self.to_temperature(sensor_index, temp_celsius)
                            else:
                                # IC temps 1-2
                                sensor_index = i + 13  # IC temps as additional sensors
                                self.to_temperature(sensor_index, temp_celsius)

    def read_csbi_can(self):
        """
        Read data from CSBI CAN frames
        Return True if successful, False otherwise
        """
        # check if all needed data is available
        data_check = 0

        try:
            # Check if CAN transport interface is available
            if not hasattr(self, 'can_transport_interface') or self.can_transport_interface is None:
                logger.error("CAN transport interface not available")
                return False
                
            if not hasattr(self.can_transport_interface, 'can_message_cache_callback'):
                logger.error("CAN message cache callback not available")
                return False
                
            # Get CAN message cache with proper type handling
            can_cache = getattr(self.can_transport_interface, 'can_message_cache_callback', None)
            if can_cache is None:
                logger.error("CAN message cache callback not available")
                return False
                
            message_cache = can_cache()
            if not isinstance(message_cache, dict):
                logger.error("Invalid CAN message cache format")
                return False
                
            for frame_id, data in message_cache.items():
                normalized_arbitration_id = frame_id + self.device_address

                # Cell voltage frames (Module1 only)
                frame_type = None
                for frame_name, frame_ids in self.CAN_FRAMES.items():
                    if normalized_arbitration_id in frame_ids:
                        frame_type = frame_name
                        break
                
                if frame_type and frame_type.startswith("CELL_VOLT"):
                    # Parse cell voltages using CSBI protocol
                    self.update_cell_voltages_from_frame(frame_type, data)
                    data_check += 1
                    
                elif frame_type and (frame_type.startswith("CELL_TEMP") or frame_type.startswith("PCB_TEMP")):
                    # Parse temperature data using the proven monitor logic
                    self.update_temperatures_from_frame(frame_type, data)
                    data_check += 1

        except Exception as e:
            logger.error(f"Error reading CSBI CAN data: {e}")
            return False

        # Check if we received any data
        if data_check == 0:
            logger.error(">>> ERROR: No CSBI CAN data received - returning")
            return False

        # Set hardware version if not set
        if self.hardware_version is None:
            self.hardware_version = f"CSBI CAN {self.cell_count}S"

        return True
