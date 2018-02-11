#!/usr/bin/python3
import time
import serial
import atexit
import sys
import struct
import functools
import itertools
from operator import xor
_responses = {}
port = sys.argv[1]

ZIGATE_CHIP_ID = 0x10408686
ZIGATE_BINARY_VERSION = bytes.fromhex('07030008')

class Command:

    def __init__(self, type_, fmt=None, raw=False):
        assert not (raw and fmt), 'Raw commands cannot use built-in struct formatting'

        self.type = type_
        self.raw = raw
        if fmt:
            self.struct = struct.Struct(fmt)
        else:
            self.struct = None

    def __call__(self, func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            rv = func(*args, **kwargs)

            if self.struct:
                try:
                    data = self.struct.pack(*rv)
                except TypeError:
                    data = self.struct.pack(rv)
            elif self.raw:
                data = rv
            else:
                data = bytearray()

            return prepare(self.type, data)

        return wrapper


class Response:

    def __init__(self, type_, data, chksum):
        self.type = type_
        self.data = data[1:]
        self.chksum = chksum
        self.status = data[0]

    @property
    def ok(self):
        return self.status == 0

    def __str__(self):
        return 'Response(type=0x%02x, data=0x%s, checksum=0x%02x)' % (
                self.type, self.data.hex(), self.chksum)



def register(type_):
    assert type_ not in _responses, 'Duplicate response type 0x%02x' % type_

    def decorator(func):
        _responses[type_] = func
        return func

    return decorator



def prepare(type_, data):
    length = len(data) + 2

    checksum = functools.reduce(xor, itertools.chain(
            type_.to_bytes(2, 'big'),
            length.to_bytes(2, 'big'),
            data), 0)

    message = struct.pack('!BB%dsB' % len(data), length, type_, data, checksum)
    #print('Prepared command 0x%s' % message.hex())
    return message


def read_response(ser):
    length = ser.read()
    length = int.from_bytes(length, 'big')
    answer = ser.read(length)
    return _unpack_raw_message(length, answer)
    type_, data, chksum = struct.unpack('!B%dsB' % (length - 2), answer)
    return {'type': type_, 'data': data, 'chksum': chksum}


def _unpack_raw_message(length, decoded):
    if len(decoded) != length or length < 2:
        print ("Unpack failed, length: %d, msg %s" % (length, decoded.hex()))
        return False
    type_, data, chksum = \
            struct.unpack('!B%dsB' % (length - 2), decoded)
    return _responses.get(type_, Response)(type_, data, chksum)

@Command(0x07)
def req_flash_erase():
    pass

@Command(0x09, raw=True)
def req_flash_write(addr, data):
    msg = struct.pack('<L%ds' % len(data), addr, data)
    return msg

@Command(0x0b, '<LH')
def req_flash_read(addr, length):
    return (addr, length)

@Command(0x1f, '<LH')
def req_ram_read(addr, length):
    return (addr, length)

@Command(0x25)
def req_flash_id():
    pass


@Command(0x27, '!B')
def req_change_baudrate(rate):
    #print(serial.Serial.BAUDRATES)
    clockspeed = 1000000
    divisor = round(clockspeed / rate)
    #print(divisor)
    return divisor


@Command(0x2c, '<BL')
def req_select_flash_type(type_, custom_jump=0):
    return (type_, custom_jump)

@Command(0x32)
def req_chip_id():
    pass




@register(0x26)
class ReadFlashIDResponse(Response):

    def __init__(self, *args):
        super().__init__(*args)
        self.manufacturer_id, self.device_id = struct.unpack('!BB', self.data)

    def __str__(self):
        return 'ReadFlashIDResponse %d (ok=%s, manufacturer_id=0x%02x, device_id=0x%02x)' % (self.status, self.ok, self.manufacturer_id, self.device_id)


@register(0x28)
class ChangeBaudrateResponse(Response):

    def __init__(self, *args):
        super().__init__(*args)

    def __str__(self):
        return 'ChangeBaudrateResponse %d (ok=%s)' % (self.status, self.ok)


@register(0x33)
class GetChipIDResponse(Response):

    def __init__(self, *args):
        super().__init__(*args)
        (self.chip_id,) = struct.unpack('!L', self.data)

    def __str__(self):
        return 'GetChipIDResponse (ok=%s, chip_id=0x%04x)' % (self.ok, self.chip_id)



ser = serial.Serial(port,  38400, timeout=5)  # open serial port

atexit.register(ser.write, req_change_baudrate(38400))

ser.write(req_change_baudrate(115200))

res = read_response(ser)
if not res or not res.ok:
    print('Change baudrate failed')
    raise SystemExit(1)

ser.baudrate = 115200

ser.write(req_chip_id())

res = read_response(ser)
if not res or not res.ok:
    print('Getting Chip ID failed')
    raise SystemExit(1)

if res.chip_id != ZIGATE_CHIP_ID:
    print('This is not a supported chip, patches welcome')
    raise SystemExit(1)

ser.write(req_flash_id())
res = read_response(ser)

if not res or not res.ok:
    print('Getting Flash ID failed')
    raise SystemExit(1)

if res.manufacturer_id != 0xcc or res.device_id != 0xee:
    print('Unsupported Flash ID, patches welcome')
    raise SystemExit(1)
else:
    flash_type = 8

ser.write(req_ram_read(0x01001570, 8))
res = read_response(ser)
#print (res.ok)
#print (res.data)
if res.data == bytes.fromhex('ffffffffffffffff'):

    ser.write(req_ram_read(0x01001580, 8))
    res = read_response(ser)
#print (res.ok)
print('Found MAC-address: %s' % ':'.join(''.join(x) for x in zip(*[iter(res.data.hex())]*2)))

ser.write(req_select_flash_type(8))
res = read_response(ser)
if not res or not res.ok:
    print('Selecting flash type failed')
    raise SystemExit(1)

flash_start = cur = 0x00000000
flash_end = 0x00040000

print('reading old flash to /tmp/old_flash.bin')
with open('/tmp/old_flash.bin', 'wb') as fd:
    fd.write(ZIGATE_BINARY_VERSION)
    read_bytes = 128
    while cur < flash_end:
        if cur + read_bytes > flash_end:
            read_bytes = flash_end - cur
        ser.write(req_flash_read(cur, read_bytes))
        res = read_response(ser)
        if cur == 0:
            (flash_end,) = struct.unpack('>L', res.data[0x20:0x24])
        fd.write(res.data)
        cur += read_bytes

print('writing new flash from /tmp/new_flash.bin')
with open('/tmp/new_flash.bin', 'rb') as fd:
    ser.write(req_flash_erase())
    res = read_response(ser)
    if not res or not res.ok:
        print('Erasing flash failed')
        raise SystemExit(1)

    flash_start = cur = 0x00000000
    flash_end = 0x00040000

    bin_ver = fd.read(4)
    if bin_ver != ZIGATE_BINARY_VERSION:
        print('Not a valid image for Zigate')
        raise SystemExit(1)
    read_bytes = 128
    while cur < flash_end:
        data = fd.read(read_bytes)
        if not data:
            break
        ser.write(req_flash_write(cur, data))
        res = read_response(ser)
        if not res.ok:
            print('writing failed at 0x%08x, status: 0x%x, data: %s' % (cur, res.status, data.hex()))
            raise SystemExit(1)
        cur += read_bytes
