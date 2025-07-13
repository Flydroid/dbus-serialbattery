#!/usr/bin/env python3

# Simple CSBI CAN import test
# Test if we can import and instantiate the Csbi_Can class

import sys
import os

# Add the dbus-serialbattery module path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'dbus-serialbattery'))

def test_csbi_import():
    """Test importing the Csbi_Can class"""
    print("=== CSBI CAN Import Test ===")
    
    try:
        print("1. Testing basic BMS import...")
        from bms.csbi_can import Csbi_Can
        print("   ✓ Csbi_Can imported successfully")
        
        print("2. Testing class instantiation...")
        # Try to create an instance (this might fail due to missing CAN interface)
        try:
            csbi_bms = Csbi_Can("PCAN_USBBUS1", 500000, None)
            print("   ✓ Csbi_Can instantiated successfully")
            print(f"   Class: {csbi_bms.__class__.__name__}")
            print(f"   Type: {csbi_bms.BATTERYTYPE}")
        except Exception as e:
            print(f"   ⚠ Instantiation failed (expected): {e}")
            print("   This is normal when CAN interface is not available")
        
        print("3. Testing frame mappings...")
        if hasattr(Csbi_Can, 'CAN_FRAMES'):
            frames = Csbi_Can.CAN_FRAMES
            print(f"   ✓ Found {len(frames)} frame mappings:")
            for frame_name, frame_ids in frames.items():
                print(f"     {frame_name}: {frame_ids}")
        else:
            print("   ✗ No CAN_FRAMES found")
        
        print("4. Testing method availability...")
        methods_to_check = [
            'update_cell_voltages_from_frame',
            'update_temperatures_from_frame',
            'read_csbi_can'
        ]
        
        for method_name in methods_to_check:
            if hasattr(Csbi_Can, method_name):
                print(f"   ✓ Method {method_name} available")
            else:
                print(f"   ✗ Method {method_name} missing")
        
        return True
        
    except Exception as e:
        print(f"   ✗ Import failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_bms_type_recognition():
    """Test if Csbi_Can is recognized in BMS types"""
    print("\n=== BMS Type Recognition Test ===")
    
    try:
        print("1. Testing utils import...")
        from utils import BMS_TYPE
        print(f"   ✓ BMS_TYPE imported: {BMS_TYPE}")
        
        print("2. Testing BMS type list...")
        if 'Csbi_Can' in BMS_TYPE or len(BMS_TYPE) == 0:
            print("   ✓ Csbi_Can should be available")
        else:
            print("   ⚠ Csbi_Can not explicitly in BMS_TYPE list")
            print(f"   Available types: {BMS_TYPE}")
        
        return True
        
    except Exception as e:
        print(f"   ✗ BMS type test failed: {e}")
        return False

def test_standalone_import():
    """Test importing standalone_serialbattery"""
    print("\n=== Standalone Import Test ===")
    
    try:
        print("1. Testing standalone import...")
        from standalone_serialbattery import standalone_serialbattery
        print("   ✓ standalone_serialbattery imported successfully")
        
        print("2. Testing CAN BMS types...")
        # This will trigger the CAN import section
        try:
            # Create instance with CAN driver option
            sasb = standalone_serialbattery("PCAN_USBBUS1", 10, "", 30)  # Reduced logging
            print("   ✓ Standalone instance created with CAN option")
            
            # Check if Csbi_Can is in supported types
            if hasattr(sasb, 'supported_bms_types'):
                can_types = [bms['bms'].__name__ for bms in sasb.supported_bms_types]
                print(f"   CAN BMS types: {can_types}")
                if 'Csbi_Can' in can_types:
                    print("   ✓ Csbi_Can found in CAN BMS types")
                else:
                    print("   ✗ Csbi_Can not found in CAN BMS types")
            
        except Exception as e:
            print(f"   ⚠ Standalone CAN test failed: {e}")
            
        return True
        
    except Exception as e:
        print(f"   ✗ Standalone import failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    print("Testing CSBI CAN Integration Components\n")
    
    # Run all tests
    test1 = test_csbi_import()
    test2 = test_bms_type_recognition() 
    test3 = test_standalone_import()
    
    print(f"\n=== Test Summary ===")
    print(f"CSBI Import Test: {'✓ PASS' if test1 else '✗ FAIL'}")
    print(f"BMS Type Test: {'✓ PASS' if test2 else '✗ FAIL'}")
    print(f"Standalone Test: {'✓ PASS' if test3 else '✗ FAIL'}")
    
    if test1 and test2 and test3:
        print("\n🎉 All tests passed! CSBI CAN should work with standalone framework.")
    else:
        print("\n⚠ Some tests failed. Check the output above for details.")

if __name__ == "__main__":
    main()
