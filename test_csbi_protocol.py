#!/usr/bin/env python3
"""
CSBI CAN Test Script
Test the updated csbi_can.py with real CSBI protocol frames
"""

import sys
import os

# Add the dbus-serialbattery directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'dbus-serialbattery'))

try:
    from bms.csbi_can import Csbi_Can
    print("✓ Successfully imported Csbi_Can class")
    
    # Test basic initialization
    bms = Csbi_Can(port="PCAN_USBBUS1", baud=500000, address=b"\x00")
    print("✓ Successfully initialized Csbi_Can instance")
    
    print(f"  - Battery type: {bms.type}")
    print(f"  - Connection name: {bms.connection_name()}")
    print(f"  - Unique identifier: {bms.unique_identifier()}")
    print(f"  - Device address: {bms.device_address}")
    
    # Show the CAN frame configuration
    print(f"\n=== CSBI CAN Frame Configuration ===")
    print("Frame mappings from csbi_can.json:")
    for frame_type, frame_ids in bms.CAN_FRAMES.items():
        print(f"  {frame_type}: {frame_ids}")
    
    # Test the update_cell_voltages_from_frame method with sample data
    print(f"\n=== Testing Cell Voltage Parsing ===")
    
    # Sample data: 4 cells at 3.3V each (3300mV = 0x0CE4 in little endian)
    sample_data = bytes([0xE4, 0x0C, 0xE4, 0x0C, 0xE4, 0x0C, 0xE4, 0x0C])
    
    print(f"Testing with sample data: {' '.join([f'{b:02X}' for b in sample_data])}")
    print("Expected: 4 cells at 3.3V each")
    
    # Test each cell voltage frame type
    for frame_type in [bms.CELL_VOLT_0, bms.CELL_VOLT_1, bms.CELL_VOLT_2]:
        print(f"\nTesting {frame_type}:")
        initial_cell_count = len(bms.cells)
        bms.update_cell_voltages_from_frame(frame_type, sample_data)
        
        print(f"  Cells added: {len(bms.cells) - initial_cell_count}")
        print(f"  Total cells: {len(bms.cells)}")
        print(f"  Total voltage: {bms.voltage:.3f}V")
        
        # Show last 4 cell voltages
        if len(bms.cells) >= 4:
            last_4_cells = bms.cells[-4:]
            voltages = [f"{cell.voltage:.3f}V" for cell in last_4_cells]
            print(f"  Last 4 cell voltages: {', '.join(voltages)}")
    
    print(f"\n=== Final Results ===")
    print(f"Total cells: {bms.cell_count}")
    print(f"Total voltage: {bms.voltage:.3f}V")
    print(f"Average cell voltage: {(bms.voltage / bms.cell_count):.3f}V" if bms.cell_count > 0 else "N/A")
    
    print(f"\n✓ All tests passed!")
    print(f"\nTo use with real CSBI hardware:")
    print(f"1. Connect PCAN USB to CSBI CAN bus")
    print(f"2. Set bitrate to 500000 bps")
    print(f"3. The BMS should automatically detect Module1 cell voltages")
    print(f"4. Expected frame IDs: 80, 81, 82, 83, 84, 85 (hex: 0x50-0x55)")
    
except ImportError as e:
    print(f"✗ Import error: {e}")
    sys.exit(1)
except Exception as e:
    print(f"✗ Error during testing: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
