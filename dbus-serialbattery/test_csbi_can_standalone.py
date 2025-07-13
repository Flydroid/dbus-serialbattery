#!/usr/bin/env python3

# NOTES
# CSBI CAN BMS Test Script
# Based on standalone_serialbattery_test.py but adapted for CAN interface
# Tests the csbi_can.py implementation using the standalone framework

import sys
import signal
import atexit
import datetime
import os
from time import sleep
import logging

# Add the dbus-serialbattery module path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'dbus-serialbattery'))

from standalone_serialbattery import standalone_serialbattery

# CAN interface configuration
# PCAN USB interface
DEVPATH = "PCAN_USBBUS1"  # PCAN USB interface
USEDIDADR = 0  # CAN address (0 for default)

# Driver option for CAN interface
DRIVEROPTION = 10  # 10 = CAN interface

# Enter Loglevel 0,10,20,30,40,50
# CRITICAL   50
# ERROR      40
# WARNING    30
# INFO       20
# DEBUG      10
# NOTSET      0
LOGLEVEL = 20
logtofile = 0
logtoconsole = 1
logpath = "csbi_can_test.log"

##################################################################
##################################################################

def on_exit():
    print("CLEAN UP ...")
    if 'sasb' in globals():
        sasb.bms_close()

def handle_exit(signum, frame):
    sys.exit(0)

# ### Main
atexit.register(on_exit)
signal.signal(signal.SIGTERM, handle_exit)
signal.signal(signal.SIGINT, handle_exit)

mylogs = logging.getLogger("CSBI_CAN_TEST")
mylogs.setLevel(LOGLEVEL)

if logtofile == 1:
    file = logging.FileHandler(logpath, mode="a")
    file.setLevel(LOGLEVEL)
    fileformat = logging.Formatter("%(asctime)s:%(module)s:%(levelname)s:%(message)s", datefmt="%H:%M:%S")
    file.setFormatter(fileformat)
    mylogs.addHandler(file)

if logtoconsole == 1:
    stream = logging.StreamHandler()
    stream.setLevel(LOGLEVEL)
    streamformat = logging.Formatter("%(asctime)s:%(module)s:%(levelname)s:%(message)s", datefmt="%H:%M:%S")
    stream.setFormatter(streamformat)
    mylogs.addHandler(stream)

print("=== CSBI CAN BMS Test ===")
print("Testing CSBI CAN BMS implementation using standalone framework")
print(f"CAN Interface: {DEVPATH}")
print(f"Driver Option: {DRIVEROPTION} (CAN)")
print(f"Log Level: {LOGLEVEL}")
print("="*60)

try:
    # Initialize standalone serialbattery with CAN parameters
    print("Creating standalone_serialbattery instance...")
    sasb = standalone_serialbattery(DEVPATH, DRIVEROPTION, "", LOGLEVEL)
    
    print("Opening CAN connection...")
    sasb.bms_open()
    sleep(2)  # Give more time for CAN initialization
    
    print("Reading BMS data...")
    time1 = datetime.datetime.now()
    ST = sasb.bms_read()
    runtime = (datetime.datetime.now() - time1).total_seconds()
    print(f"Runtime: {runtime:.3f} seconds")
    
    if ST:
        print("\n=== BMS DETECTION SUCCESS ===")
        print(f"BMS Type: {sasb.battery[0].__class__.__name__ if sasb.battery[0] else 'Unknown'}")
        print(f"Hardware Version: {getattr(sasb.battery[0], 'hardware_version', 'Not available')}")
        
        # Display cell information
        print(f"\n=== CELL INFORMATION ===")
        print(f"Cell count: {sasb.cell_count}")
        
        if sasb.cell_count > 0:
            total_voltage = 0
            min_voltage = float('inf')
            max_voltage = float('-inf')
            
            print("Cell voltages:")
            for i in range(sasb.cell_count):
                cell_voltage = sasb.cells[i] / 1000  # Convert from mV to V
                total_voltage += cell_voltage
                min_voltage = min(min_voltage, cell_voltage)
                max_voltage = max(max_voltage, cell_voltage)
                print(f"  Cell {i+1:2d}: {cell_voltage:.3f}V")
            
            print(f"\nVoltage summary:")
            print(f"  Total: {total_voltage:.3f}V")
            print(f"  Average: {total_voltage/sasb.cell_count:.3f}V")
            print(f"  Min: {min_voltage:.3f}V | Max: {max_voltage:.3f}V | Diff: {max_voltage-min_voltage:.3f}V")
        
        # Display temperature information
        print(f"\n=== TEMPERATURE INFORMATION ===")
        temps_found = 0
        
        if hasattr(sasb, 'temperature_fet') and sasb.temperature_fet is not None:
            print(f"Temperature FET: {sasb.temperature_fet}°C")
            temps_found += 1
            
        if hasattr(sasb, 'temperature_1') and sasb.temperature_1 is not None:
            print(f"Temperature 1: {sasb.temperature_1}°C")
            temps_found += 1
            
        if hasattr(sasb, 'temperature_2') and sasb.temperature_2 is not None:
            print(f"Temperature 2: {sasb.temperature_2}°C")
            temps_found += 1
        
        # Check for additional temperature sensors
        battery_obj = sasb.battery[0]
        if battery_obj and hasattr(battery_obj, 'temp1') and battery_obj.temp1 is not None:
            print(f"Battery Temp 1: {battery_obj.temp1}°C")
            temps_found += 1
            
        if battery_obj and hasattr(battery_obj, 'temp2') and battery_obj.temp2 is not None:
            print(f"Battery Temp 2: {battery_obj.temp2}°C")
            temps_found += 1
            
        if battery_obj and hasattr(battery_obj, 'temp3') and battery_obj.temp3 is not None:
            print(f"Battery Temp 3: {battery_obj.temp3}°C")
            temps_found += 1
            
        if battery_obj and hasattr(battery_obj, 'temp4') and battery_obj.temp4 is not None:
            print(f"Battery Temp 4: {battery_obj.temp4}°C")
            temps_found += 1
        
        if temps_found == 0:
            print("No temperature data available")
        
        # Display other battery information
        print(f"\n=== BATTERY INFORMATION ===")
        if hasattr(sasb, 'voltage') and sasb.voltage is not None:
            print(f"Battery Voltage: {sasb.voltage / 100:.2f}V")
            
        if hasattr(sasb, 'act_current') and sasb.act_current is not None:
            current_a = sasb.act_current / 100
            print(f"Current: {current_a:.2f}A {'(Discharge)' if current_a > 0 else '(Charge)' if current_a < 0 else '(Idle)'}")
            
        if hasattr(sasb, 'soc') and sasb.soc is not None:
            print(f"State of Charge: {sasb.soc}%")
            
        if hasattr(sasb, 'voltage') and hasattr(sasb, 'act_current') and sasb.voltage and sasb.act_current:
            power_w = int((sasb.voltage * sasb.act_current) / 10000)
            print(f"Power: {power_w}W")
        
        print(f"\n=== TEST COMPLETED SUCCESSFULLY ===")
        
    else:
        print("\n=== BMS DETECTION FAILED ===")
        print("No data returned from BMS")
        print("Possible issues:")
        print("- CSBI BMS not connected or powered")
        print("- CAN interface not properly configured")
        print("- Wrong CAN bitrate (should be 500000 bps)")
        print("- PCAN USB device not available")
        
except Exception as e:
    print(f"\n=== ERROR DURING TEST ===")
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
    
    print("\nTroubleshooting:")
    print("1. Check PCAN USB device is connected and recognized")
    print("2. Verify CSBI BMS is powered and transmitting CAN frames")
    print("3. Ensure CAN bitrate is set to 500000 bps")
    print("4. Check that no other software is using the PCAN device")
    print("5. Verify python-can[pcan] is installed")

finally:
    print(f"\nCleaning up...")
    
sys.exit(0)
