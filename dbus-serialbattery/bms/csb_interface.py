# -*- coding: utf-8 -*-

# NOTES
# Please see "Add/Request a new BMS" https://louisvdw.github.io/dbus-serialbattery/general/supported-bms#add-by-opening-a-pull-request
# in the documentation for a checklist what you have to do, when adding a new BMS

# avoid importing wildcards
from battery import Protection, Battery, Cell
from utils import is_bit_set, read_serial_data, logger
import utils
from struct import unpack_from





class CSB_Interface(Battery):
    def __init__(self, port, baud, address):
        super(CSB_Interface, self).__init__(port, baud, address)
        self.type = self.BATTERYTYPE
        self.cell_count = 24

    BATTERYTYPE = "NV GenD"
    LENGTH_CHECK = 0
    LENGTH_POS = 0 # expecting 73 bytes for each frame
    LENGTH_SIZE = None
    LENGTH_FIXED = 89



    def test_connection(self):
        # call a function that will connect to the battery, send a command and retrieve the result.
        # The result or call should be unique to this BMS. Battery name or version, etc.
        # Return True if success, False for failure
        result = False
        try:
            result = self.read_status_data()
            # get first data to show in startup log, only if result is true
            #logger.info(result)
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
        self.cell_count=24
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
        #logger.info(cell_data)
        # check if connection success
        if cell_data is False:
            return False

        voltages,temps = self.get_VoltsAndTemps(cell_data)
        self.cells = []
        
        #if len(self.cells) != self.cell_count:
            # init the numbers of cells
        for idx in range(self.cell_count):
            self.cells.append(Cell(True))


        for idx in range(self.cell_count):
            self.cells[idx].voltage = voltages[idx]/1000

        self.temp1 = temps[0]/10
        self.temp2 = temps[1]/10
        self.temp3 = temps[2]/10
        self.temp4 = temps[3]/10

        pack_voltage = 0
        for idx in range(self.cell_count):
            pack_voltage = pack_voltage+self.cells[idx].voltage

        self.voltage = pack_voltage/2 # divide by 2 to get the average for two halfmodules
        self.current = 0
        self.soc = 0

        #logger.info("Cells %s",self.cells)
        #logger.info("temp1 %s",self.temp1)
        #logger.info("temp2 %s",self.temp2)
        #logger.info("temp3 %s",self.temp3)
        #logger.info("temp4 %s",self.temp4)

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
        crc_computed = crc16(data)    

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
        #logger.info("get_VoltsAndTemps:Values %s",values)
        voltages = values[0:24]
        temps= values[24:40]
        return voltages,temps
    
def crc16(data: bytes):
    '''
    CRC-16 (CCITT) implemented with a precomputed lookup table
    '''
    table = [ 
        0x0000, 0x1021, 0x2042, 0x3063, 0x4084, 0x50A5, 0x60C6, 0x70E7, 0x8108, 0x9129, 0xA14A, 0xB16B, 0xC18C, 0xD1AD, 0xE1CE, 0xF1EF,
        0x1231, 0x0210, 0x3273, 0x2252, 0x52B5, 0x4294, 0x72F7, 0x62D6, 0x9339, 0x8318, 0xB37B, 0xA35A, 0xD3BD, 0xC39C, 0xF3FF, 0xE3DE,
        0x2462, 0x3443, 0x0420, 0x1401, 0x64E6, 0x74C7, 0x44A4, 0x5485, 0xA56A, 0xB54B, 0x8528, 0x9509, 0xE5EE, 0xF5CF, 0xC5AC, 0xD58D,
        0x3653, 0x2672, 0x1611, 0x0630, 0x76D7, 0x66F6, 0x5695, 0x46B4, 0xB75B, 0xA77A, 0x9719, 0x8738, 0xF7DF, 0xE7FE, 0xD79D, 0xC7BC,
        0x48C4, 0x58E5, 0x6886, 0x78A7, 0x0840, 0x1861, 0x2802, 0x3823, 0xC9CC, 0xD9ED, 0xE98E, 0xF9AF, 0x8948, 0x9969, 0xA90A, 0xB92B,
        0x5AF5, 0x4AD4, 0x7AB7, 0x6A96, 0x1A71, 0x0A50, 0x3A33, 0x2A12, 0xDBFD, 0xCBDC, 0xFBBF, 0xEB9E, 0x9B79, 0x8B58, 0xBB3B, 0xAB1A,
        0x6CA6, 0x7C87, 0x4CE4, 0x5CC5, 0x2C22, 0x3C03, 0x0C60, 0x1C41, 0xEDAE, 0xFD8F, 0xCDEC, 0xDDCD, 0xAD2A, 0xBD0B, 0x8D68, 0x9D49,
        0x7E97, 0x6EB6, 0x5ED5, 0x4EF4, 0x3E13, 0x2E32, 0x1E51, 0x0E70, 0xFF9F, 0xEFBE, 0xDFDD, 0xCFFC, 0xBF1B, 0xAF3A, 0x9F59, 0x8F78,
        0x9188, 0x81A9, 0xB1CA, 0xA1EB, 0xD10C, 0xC12D, 0xF14E, 0xE16F, 0x1080, 0x00A1, 0x30C2, 0x20E3, 0x5004, 0x4025, 0x7046, 0x6067,
        0x83B9, 0x9398, 0xA3FB, 0xB3DA, 0xC33D, 0xD31C, 0xE37F, 0xF35E, 0x02B1, 0x1290, 0x22F3, 0x32D2, 0x4235, 0x5214, 0x6277, 0x7256,
        0xB5EA, 0xA5CB, 0x95A8, 0x8589, 0xF56E, 0xE54F, 0xD52C, 0xC50D, 0x34E2, 0x24C3, 0x14A0, 0x0481, 0x7466, 0x6447, 0x5424, 0x4405,
        0xA7DB, 0xB7FA, 0x8799, 0x97B8, 0xE75F, 0xF77E, 0xC71D, 0xD73C, 0x26D3, 0x36F2, 0x0691, 0x16B0, 0x6657, 0x7676, 0x4615, 0x5634,
        0xD94C, 0xC96D, 0xF90E, 0xE92F, 0x99C8, 0x89E9, 0xB98A, 0xA9AB, 0x5844, 0x4865, 0x7806, 0x6827, 0x18C0, 0x08E1, 0x3882, 0x28A3,
        0xCB7D, 0xDB5C, 0xEB3F, 0xFB1E, 0x8BF9, 0x9BD8, 0xABBB, 0xBB9A, 0x4A75, 0x5A54, 0x6A37, 0x7A16, 0x0AF1, 0x1AD0, 0x2AB3, 0x3A92,
        0xFD2E, 0xED0F, 0xDD6C, 0xCD4D, 0xBDAA, 0xAD8B, 0x9DE8, 0x8DC9, 0x7C26, 0x6C07, 0x5C64, 0x4C45, 0x3CA2, 0x2C83, 0x1CE0, 0x0CC1,
        0xEF1F, 0xFF3E, 0xCF5D, 0xDF7C, 0xAF9B, 0xBFBA, 0x8FD9, 0x9FF8, 0x6E17, 0x7E36, 0x4E55, 0x5E74, 0x2E93, 0x3EB2, 0x0ED1, 0x1EF0
    ]
    
    crc = 0xFFFF
    for byte in data:
        crc = (crc << 8) ^ table[(crc >> 8) ^ byte]
        crc &= 0xFFFF                                   # important, crc must stay 16bits all the way through
    return crc