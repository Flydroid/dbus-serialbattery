import utils
import binascii
import crcmod
from time import sleep

SERIAL_SOF = [0x1a, 0x85]
SERIAL_EOF = [0x22, 0xCE]

# Calculates and compares the CRC of a given frame starting by an SOF and finishing by an EOF
# Returns  1 if matching CRC
# Returns  0 else
def check_crc(frame):
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
def get_data_from_frame(frame):
    # Striping the frame of the EOF, CRC and SOF :
    framed = frame[5:-4]  # Getting rid of the SOF and of 

    return framed


# Returns the list of voltages
def read_voltages(data):
    voltage = []
    while len(data) > 0:
        volt = data[:2]  # Reading 2 first bytes
        int_volt = int.from_bytes(volt, byteorder='big', signed=True)
        voltage.append(int_volt)  # Converting the from hex to int
        data = data[2:]  # Getting rid of the 2 first bytes
    return voltage


ser = utils.open_serial_port("COM4",115200)
sleep(1)
buffer = utils.read_serialport_data(ser,0,length_pos=0,length_check=0, length_fixed=73)
print(buffer)
ser.close()


sof = buffer.find(bytearray(SERIAL_SOF),) 
eof = sof+ buffer[sof:].find(bytearray(SERIAL_EOF))

raw_frame = buffer[sof:eof+2]

if check_crc(raw_frame) == 1:
    frame = get_data_from_frame(raw_frame) # remove sof, eof and crc
    print(frame)
    print(read_voltages(frame))
else:
    print("CRC missmatch")