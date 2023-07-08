import utils
import binascii
import crcmod

SERIAL_SOF = [0x1a, 0x85]
SERIAL_EOF = [0x22, 0xCE]

# Returns the CRC value (int)
# Be sure to input a bytearray and not a hexlified value
def compute_crc(data):
    # Setting up the polynomial
    CRC16_CCITT = crcmod.Crc(0x11021, initCrc=0xFFFF, rev=False, xorOut=0x0000)
    data = binascii.hexlify(data)
    CRC16_CCITT.update(binascii.a2b_hex(data))  # Calculates the CRC on the given data

    return CRC16_CCITT.crcValue

# Calculates and compares the CRC of a given frame starting by an SOF and finishing by an EOF
# Returns  1 if matching CRC
# Returns  0 else
def check_crc(frame):
    data_crc = frame[2:-2] # remove sof and eof to get data + crc
    crc_retrieved = data_crc[len(data_crc) - 2:]  # Where 2 is the length of the CRC
    data = data_crc[:len(data_crc) - 2]  # Getting rid of the CRC
    # Calculating the CRC of the data in the frame
    crc_computed = compute_crc(data)

    crc_retrieved = int.from_bytes(crc_retrieved, byteorder='big', signed=False)  # Converting from hex to int

    return crc_computed == crc_retrieved


# Returns the bytearray without EOF and SOF
def get_data_from_frame(frame):
    # Striping the frame of the EOF, CRC and SOF :
    framed = frame[2:-4]  # Getting rid of the SOF and of 

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


ser = utils.open_serial_port("COM5",115200)
buffer = utils.read_serialport_data(ser,0,length_pos=0,length_check=0, length_fixed=73)
print(buffer)
ser.close()


sof = buffer.find(bytearray(SERIAL_SOF),) 
eof = sof+ buffer[sof:].find(bytearray(SERIAL_EOF))

raw_frame = buffer[sof:eof+2]

if check_crc(raw_frame) == 1:
    frame = get_data_from_frame(raw_frame) # remove sof, eof and crc
    print(frame[2:])
    print(read_voltages(frame[3:]))
else:
    print("CRC missmatch")