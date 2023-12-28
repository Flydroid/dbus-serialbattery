# -*- coding: utf-8 -*-

# NOTES
# Please see "Add/Request a new BMS" https://louisvdw.github.io/dbus-serialbattery/general/supported-bms#add-by-opening-a-pull-request
# in the documentation for a checklist what you have to do, when adding a new BMS

# avoid importing wildcards
from battery import Protection, Battery, Cell
from utils import is_bit_set, read_serial_data, logger
import utils
from struct import unpack_from
import binascii
import crcmod




class CSB_Interface(Battery):
    def __init__(self, port, baud, address):
        super(CSB_Interface, self).__init__(port, baud, address)
        self.type = self.BATTERYTYPE

    BATTERYTYPE = "NV GenD"
    LENGTH_CHECK = 0
    LENGTH_POS = 0 # expecting 73 bytes for each frame
    LENGTH_SIZE = None
    LENGTH_FIXED = 73



    def test_connection(self):
        # call a function that will connect to the battery, send a command and retrieve the result.
        # The result or call should be unique to this BMS. Battery name or version, etc.
        # Return True if success, False for failure
        result = False
        try:
            result = self.read_status_data()
            # get first data to show in startup log, only if result is true
            logger.info(result)
            if result:
                self.refresh_data()
        except Exception as err:
            logger.error(f"Unexpected {err=}, {type(err)=}")
            result = False

        return result

    def get_settings(self):
        # After successful  connection get_settings will be call to set up the battery.
        # Set the current limits, populate cell count, etc
        # Return True if success, False for failure
        self.cell_count=12
        self.capacity = (
            utils.BATTERY_CAPACITY  # if possible replace constant with value read from BMS
        )
        self.max_battery_charge_current = 30
        self.max_battery_discharge_current = 30
        self.max_battery_voltage = 4.1
        self.min_battery_voltage = 3.0

        # provide a unique identifier from the BMS to identify a BMS, if multiple same BMS are connected
        # e.g. the serial number
        # If there is no such value, please leave the line commented. In this case the capacity is used,
        # since it can be changed by small amounts to make a battery unique. On +/- 5 Ah you can identify 11 batteries
        # self.unique_identifier = str()
        return True

    def refresh_data(self):
        # call all functions that will refresh the battery data.
        # This will be called for every iteration (1 second)
        # Return True if success, False for failure
        result = self.read_cell_data()

        return result

    def read_status_data(self):
        status_data = self.read_serial_data()
        # check if connection success
        if status_data is False:
            return False

        # (
        #     self.cell_count,
        #     self.temp_sensors,
        #     self.charger_connected,
        #     self.load_connected,
        #     state,
        #     self.cycles,
        # ) = unpack_from(">bb??bhx", status_data)

        self.hardware_version = "CSB-Interface rev3"
        logger.info(self.hardware_version)
        return True

    def read_cell_data(self):
        cell_data = self.read_serial_data()
        logger.info(cell_data)
        # check if connection success
        if cell_data is False:
            return False

        voltages,temps = self.get_VoltsAndTemps(cell_data)

        self.cells = voltages
        self.temp1 = temps[0]
        self.temp2 = temps[1]
        self.temp3 = temps[2]
        self.temp4 = temps[3]
        self.voltage = sum(self.cells)
        self.current = 0
        self.soc = 0

        logger.info("Cells %s",self.cells)
        logger.info("temp1 %s",self.temp1)
        logger.info("temp2 %s",self.temp2)
        logger.info("temp3 %s",self.temp3)
        logger.info("temp4 %s",self.temp4)

        return True

    def read_serial_data(self):
        SERIAL_SOF = [0x1a, 0x85]
        SERIAL_EOF = [0x22, 0xCE]

        # use the read_serial_data() function to read the data and then do BMS spesific checks (crc, start bytes, etc)
        buffer = read_serial_data(0, self.port, self.baud_rate, self.LENGTH_POS, self.LENGTH_CHECK,self.LENGTH_FIXED,self.LENGTH_SIZE)
        if buffer is False:
            logger.error(">>> ERROR: No reply - returning")
            return False
        sof = buffer.find(bytearray(SERIAL_SOF),) 
        eof = sof+ buffer[sof:].find(bytearray(SERIAL_EOF))
        raw_frame = buffer[sof:eof+2]

        if self.check_crc(raw_frame) == 1:
            frame = self.get_data_from_frame(raw_frame) # remove sof, eof and crc
            
            return frame
        else:
            logger.error(">>> ERROR: CRC Doesn't Match")
            return False

    # Calculates and compares the CRC of a given frame starting by an SOF and finishing by an EOF
    # Returns  1 if matching CRC
    # Returns  0 else
    def check_crc(self,frame):
        data_crc = frame[2:-2] # remove sof and eof to get data + crc
        crc_retrieved = data_crc[len(data_crc) - 2:]  # Where 2 is the length of the CRC
        data = data_crc[:len(data_crc) - 2]  # Getting rid of the CRC
        # Calculating the CRC of the data in the frame
        CRC16_CCITT = crcmod.Crc(0x11021, initCrc=0xFFFF, rev=False, xorOut=0x0000)
        data = binascii.hexlify(data)
        CRC16_CCITT.update(binascii.a2b_hex(data))  # Calculates the CRC on the given data
        crc_computed = CRC16_CCITT.crcValue

        crc_retrieved = int.from_bytes(crc_retrieved, byteorder='big', signed=False)  # Converting from hex to int

        return crc_computed == crc_retrieved


    # Returns the bytearray without EOF and SOF
    def get_data_from_frame(self,frame):
        # Striping the frame of the EOF, CRC and SOF :
        data = frame[5:-4]  # Getting rid of the SOF and of 

        return data


    # Returns the list of voltages
    def get_VoltsAndTemps(self,data):
        values = []
        while len(data) > 0:
            value = data[:2]  # Reading 2 first bytes
            int_value = int.from_bytes(value, byteorder='big', signed=True)
            values.append(int_value)  # Converting the from hex to int
            data = data[2:]  # Getting rid of the 2 first bytes
        logger.info("get_VoltsAndTemps:Values %s",values)
        voltages = values[0:12]
        temps= values[12:20]
        return voltages,temps