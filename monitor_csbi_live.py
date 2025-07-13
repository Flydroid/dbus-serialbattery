#!/usr/bin/env python3
"""
Live CSBI CAN Monitor
Monitor real CSBI CAN frames using the updated protocol
"""

import can
import time
import sys
from struct import unpack

class CSBILiveMonitor:
    def __init__(self):
        self.bus = None
        self.cell_voltages = {}  # Store voltages by cell index
        self.cell_temperatures = {}   # Store cell temperatures by sensor index
        self.pcb_temperatures = {}    # Store PCB temperatures by sensor index  
        self.ic_temperatures = {}     # Store IC temperatures by sensor index
        self.frame_counts = {}   # Count frames received
        
        # CSBI frame mappings from csbi_can.json (Module1 only)
        self.csbi_frames = {
            80: {"name": "Cell_Voltages_0", "cells": [1, 2, 3, 4], "type": "voltage"},
            81: {"name": "Cell_Voltages_1", "cells": [5, 6, 7, 8], "type": "voltage"},
            82: {"name": "Cell_Voltages_2", "cells": [9, 10, 11, 12], "type": "voltage"},
            83: {"name": "Cell_Voltages_3", "cells": [13, 14, 15, 16], "type": "voltage"},
            84: {"name": "Cell_Voltages_4", "cells": [17, 18, 19, 20], "type": "voltage"},
            85: {"name": "Cell_Voltages_5", "cells": [21, 22, 23, 24], "type": "voltage"},
            # Temperature frames: Module1_Cell_Temp_1-8 (16-bit signed, 0.1°C scaling)
            1104: {"name": "Temperatures_0", "sensors": [1, 2, 3, 4], "type": "temperature", "sensor_type": "cell"},
            1105: {"name": "Temperatures_1", "sensors": [5, 6, 7, 8], "type": "temperature", "sensor_type": "cell"},
            # PCB and IC Temperature frames
            1106: {"name": "Temperatures_2", "sensors": [1, 2, 3, 4], "type": "temperature", "sensor_type": "pcb"},
            1107: {"name": "Temperatures_3", "sensors": [5, 6, 7, 8], "type": "temperature", "sensor_type": "mixed"},  # PCB5,6 + IC1,2
        }
    
    def setup_can(self, channel='PCAN_USBBUS1', bitrate=500000):
        """Setup CAN interface"""
        try:
            print(f"Connecting to {channel} at {bitrate} bps...")
            self.bus = can.interface.Bus(
                interface='pcan',
                channel=channel,
                bitrate=bitrate
            )
            print("✓ CAN connection established")
            return True
        except Exception as e:
            print(f"✗ CAN connection failed: {e}")
            return False
    
    def parse_cell_voltages(self, frame_id, data):
        """Parse cell voltages from CSBI frame"""
        if frame_id not in self.csbi_frames:
            return
            
        frame_info = self.csbi_frames[frame_id]
        
        # Handle voltage frames
        if frame_info["type"] == "voltage" and "cells" in frame_info:
            if len(data) < 8:
                return
            
            # Parse 4 cells (16-bit little endian, 0.001V scaling)
            for i in range(4):
                if i * 2 + 1 < len(data):
                    cell_num = frame_info["cells"][i]
                    raw_value = unpack("<H", data[i*2:i*2+2])[0]
                    voltage = raw_value * 0.001
                    
                    if voltage > 0:  # Only store valid voltages
                        self.cell_voltages[cell_num] = voltage
        
        # Handle temperature frames
        elif frame_info["type"] == "temperature" and "sensors" in frame_info:
            if len(data) < 8:
                return
            
            # Parse temperature data according to CSBI specification:
            # - 16-bit signed little-endian values
            # - Scaling factor: 0.1 (temps are in tenths of degrees)
            # - Different sensor types: cell, pcb, ic
            
            sensor_type = frame_info.get("sensor_type", "cell")
            
            for i in range(4):  # 4 temperature sensors per frame
                if i < len(frame_info["sensors"]) and len(data) >= (i * 2 + 2):
                    sensor_num = frame_info["sensors"][i]
                    
                    # Parse 16-bit signed little-endian value
                    temp_raw = unpack("<h", data[i*2:i*2+2])[0]  # <h for signed 16-bit
                    
                    if temp_raw != 0:  # Skip zero values (likely invalid)
                        # Apply CSBI scaling: 0.1 degrees per unit
                        temp_celsius = temp_raw * 0.1
                        
                        # Store if temperature is reasonable (-40°C to 85°C)
                        if -40 <= temp_celsius <= 85:
                            # Store in appropriate temperature dictionary based on sensor type
                            if sensor_type == "cell":
                                self.cell_temperatures[sensor_num] = temp_celsius
                            elif sensor_type == "pcb":
                                self.pcb_temperatures[sensor_num] = temp_celsius
                            elif sensor_type == "mixed":
                                # Frame 1107: PCB_Temp_5,6 + IC_Temp_1,2
                                if i < 2:  # First two are PCB temps (5,6)
                                    self.pcb_temperatures[sensor_num] = temp_celsius
                                else:  # Last two are IC temps (1,2)
                                    ic_num = i - 1  # Convert to IC sensor numbers (1,2)
                                    self.ic_temperatures[ic_num] = temp_celsius
    
    def print_status(self):
        """Print current status"""
        # Print header
        print("="*60)
        print(f"=== CSBI Live Monitor === Time: {time.strftime('%H:%M:%S')}")
        print("="*60)
        
        # Print cell voltages
        if self.cell_voltages:
            sorted_cells = sorted(self.cell_voltages.keys())
            total_voltage = sum(self.cell_voltages.values())
            
            print(f"\n=== CELL VOLTAGES ===")
            print(f"Cells detected: {len(self.cell_voltages)}")
            print(f"Total voltage: {total_voltage:.3f}V")
            print(f"Average voltage: {total_voltage/len(self.cell_voltages):.3f}V")
            
            # Find min/max voltages
            min_voltage = min(self.cell_voltages.values())
            max_voltage = max(self.cell_voltages.values())
            min_cell = [k for k, v in self.cell_voltages.items() if v == min_voltage][0]
            max_cell_num = [k for k, v in self.cell_voltages.items() if v == max_voltage][0]
            
            print(f"Min: C{min_cell:02d}={min_voltage:.3f}V | Max: C{max_cell_num:02d}={max_voltage:.3f}V | Diff: {max_voltage-min_voltage:.3f}V")
            
            # Print ALL cells in rows of 6 (more compact)
            print("\nAll Cell Voltages:")
            for i in range(0, len(sorted_cells), 6):
                row_cells = []
                for j in range(6):
                    if i + j < len(sorted_cells):
                        cell_num = sorted_cells[i + j]
                        voltage = self.cell_voltages[cell_num]
                        row_cells.append(f"C{cell_num:02d}:{voltage:.3f}V")
                if row_cells:
                    print(f"  {' | '.join(row_cells)}")
        else:
            print(f"\n=== CELL VOLTAGES ===")
            print("No cell data received yet...")
        
        # Print temperatures by category
        print(f"\n=== TEMPERATURES ===")
        
        # Cell temperatures
        if self.cell_temperatures:
            sorted_cell_temps = sorted(self.cell_temperatures.keys())
            min_temp = min(self.cell_temperatures.values())
            max_temp = max(self.cell_temperatures.values())
            avg_temp = sum(self.cell_temperatures.values()) / len(self.cell_temperatures)
            
            print(f"Cell Temperatures ({len(self.cell_temperatures)} sensors):")
            print(f"  Min: {min_temp:.1f}°C | Max: {max_temp:.1f}°C | Avg: {avg_temp:.1f}°C")
            
            # Print cell temperatures in rows of 4
            for i in range(0, len(sorted_cell_temps), 4):
                row_temps = []
                for j in range(4):
                    if i + j < len(sorted_cell_temps):
                        sensor_num = sorted_cell_temps[i + j]
                        temp = self.cell_temperatures[sensor_num]
                        row_temps.append(f"CT{sensor_num:02d}:{temp:+5.1f}°C")
                if row_temps:
                    print(f"  {' | '.join(row_temps)}")
        else:
            print("Cell Temperatures: No data received yet...")
        
        # PCB temperatures
        if self.pcb_temperatures:
            sorted_pcb_temps = sorted(self.pcb_temperatures.keys())
            min_temp = min(self.pcb_temperatures.values())
            max_temp = max(self.pcb_temperatures.values())
            avg_temp = sum(self.pcb_temperatures.values()) / len(self.pcb_temperatures)
            
            print(f"\nPCB Temperatures ({len(self.pcb_temperatures)} sensors):")
            print(f"  Min: {min_temp:.1f}°C | Max: {max_temp:.1f}°C | Avg: {avg_temp:.1f}°C")
            
            # Print PCB temperatures in rows of 4
            for i in range(0, len(sorted_pcb_temps), 4):
                row_temps = []
                for j in range(4):
                    if i + j < len(sorted_pcb_temps):
                        sensor_num = sorted_pcb_temps[i + j]
                        temp = self.pcb_temperatures[sensor_num]
                        row_temps.append(f"PT{sensor_num:02d}:{temp:+5.1f}°C")
                if row_temps:
                    print(f"  {' | '.join(row_temps)}")
        else:
            print("\nPCB Temperatures: No data received yet...")
        
        # IC temperatures  
        if self.ic_temperatures:
            sorted_ic_temps = sorted(self.ic_temperatures.keys())
            min_temp = min(self.ic_temperatures.values())
            max_temp = max(self.ic_temperatures.values())
            avg_temp = sum(self.ic_temperatures.values()) / len(self.ic_temperatures)
            
            print(f"\nIC Temperatures ({len(self.ic_temperatures)} sensors):")
            print(f"  Min: {min_temp:.1f}°C | Max: {max_temp:.1f}°C | Avg: {avg_temp:.1f}°C")
            
            # Print IC temperatures in one row
            row_temps = []
            for sensor_num in sorted_ic_temps:
                temp = self.ic_temperatures[sensor_num]
                row_temps.append(f"IT{sensor_num:02d}:{temp:+5.1f}°C")
            if row_temps:
                print(f"  {' | '.join(row_temps)}")
        else:
            print("\nIC Temperatures: No data received yet...")
        
        # Print frame statistics
        if self.frame_counts:
            print(f"\n=== FRAME STATISTICS ===")
            voltage_frames = 0
            temp_frames = 0
            other_frames = 0
            
            # Group frames by type
            csbi_frames_found = []
            other_frames_found = []
            
            for frame_id, count in sorted(self.frame_counts.items()):
                if frame_id in self.csbi_frames:
                    name = self.csbi_frames[frame_id]["name"]
                    frame_type = self.csbi_frames[frame_id]["type"]
                    csbi_frames_found.append((frame_id, name, frame_type, count))
                    if frame_type == "voltage":
                        voltage_frames += count
                    elif frame_type == "temperature":
                        temp_frames += count
                else:
                    other_frames_found.append((frame_id, count))
                    other_frames += count
            
            # Print CSBI frames
            if csbi_frames_found:
                print("CSBI Frames:")
                for frame_id, name, frame_type, count in csbi_frames_found:
                    print(f"  ID {frame_id:4d} (0x{frame_id:03X}) {name:18s} [{frame_type:11s}]: {count:6d} frames")
            
            # Print other frames (if any)
            if other_frames_found:
                print("Other Frames:")
                for frame_id, count in other_frames_found[:5]:  # Limit to first 5
                    print(f"  ID {frame_id:4d} (0x{frame_id:03X}) {'Unknown':18s} {'[other]':11s}: {count:6d} frames")
                if len(other_frames_found) > 5:
                    print(f"  ... and {len(other_frames_found) - 5} more")
            
            print(f"Summary: Voltage={voltage_frames}, Temperature={temp_frames}, Other={other_frames}")
        
        print(f"\nPress Ctrl+C to stop...")
        print("="*60)
    
    def monitor(self, duration=None):
        """Monitor CAN frames"""
        if not self.bus:
            print("CAN bus not connected")
            return
        
        print(f"Starting CSBI monitoring...")
        print(f"Looking for Module1 frames: {list(self.csbi_frames.keys())}")
        print(f"Monitoring: Cell voltages (80-85), Cell temps (1104-1105), PCB temps (1106-1107), IC temps (1107)")
        print(f"Press Ctrl+C to stop\n")
        
        start_time = time.time()
        last_update = 0
        
        try:
            while True:
                # Check for duration limit
                if duration and (time.time() - start_time) > duration:
                    break
                
                # Receive CAN message
                message = self.bus.recv(timeout=1.0)
                
                if message:
                    frame_id = message.arbitration_id
                    
                    # Count all frames
                    self.frame_counts[frame_id] = self.frame_counts.get(frame_id, 0) + 1
                    
                    # Parse CSBI frames
                    if frame_id in self.csbi_frames:
                        self.parse_cell_voltages(frame_id, message.data)
                
                # Update display every 5 seconds (longer interval for better readability)
                current_time = time.time()
                if current_time - last_update > 5.0:
                    # Clear the screen properly on Windows
                    import os
                    os.system('cls' if os.name == 'nt' else 'clear')
                    self.print_status()
                    last_update = current_time
                    
        except KeyboardInterrupt:
            print(f"\n\nMonitoring stopped by user")
        finally:
            if self.bus:
                self.bus.shutdown()

def main():
    print("=== CSBI CAN Live Monitor ===")
    print("Monitoring CSBI Module1 cell voltages, cell temperatures, PCB temperatures, and IC temperatures in real-time")
    
    monitor = CSBILiveMonitor()
    
    # Try to connect
    if not monitor.setup_can():
        print("\nTroubleshooting:")
        print("1. Check PCAN USB device is connected")
        print("2. Verify CSBI BMS is powered and transmitting")
        print("3. Check CAN bitrate (trying 500000 bps)")
        print("4. Ensure no other software is using PCAN device")
        return
    
    # Start monitoring
    try:
        monitor.monitor()
    except Exception as e:
        print(f"Error during monitoring: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
