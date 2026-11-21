"""Bounded DIET 1.44 streams with the DOS stub and an ARC checksum.

The compressed-data grammar is documented at
https://entropymine.wordpress.com/2023/08/15/how-diet-compression-works/
"""

import re

from ..formats import AssetError

MAGIC = bytes.fromhex('b44ccd219d89646c7a')
HEADER = 17
MAX_OUTPUT = 4*1024*1024


def _crc_table():
    values = []
    for n in range(256):
        for _ in range(8):
            n = (n>>1) ^ (0xa001 if n&1 else 0)
        values.append(n)
    return tuple(values)


_CRC = _crc_table()


class _Stream:
    def __init__(self,data):
        self.data = data
        self.at = 0
        self.bits_left = 0
        self.flags = 0
        self.refill()

    def byte(self):
        if self.at == len(self.data):
            raise AssetError('The DIET stream ends early.')
        value = self.data[self.at]
        self.at += 1
        return value

    def refill(self):
        self.flags = self.byte() | self.byte()<<8
        self.bits_left = 16

    def bit(self):
        value = self.flags&1
        self.flags >>= 1
        self.bits_left -= 1
        if not self.bits_left:
            self.refill()
        return value

    def bits(self,count):
        value = 0
        for _ in range(count):
            value = 2*value+self.bit()
        return value

    def distance(self,low):
        high = self.bit()
        if self.bit():
            return 512-256*high-low
        if self.bit():
            return 1024-256*high-low
        for limit in (2048,4096,8192):
            high = 2*high+self.bit()
            if limit == 8192 or self.bit():
                return limit-256*high-low

    def length(self):
        for length in range(3,7):
            if self.bit():
                return length
        if self.bit():
            return 7+self.bit()
        if self.bit():
            return 17+self.byte()
        return 9+self.bits(3)


def unpack(image, offset, *, check=lambda: None):
    if offset < 0 or offset+HEADER > len(image) or image[offset:offset+len(MAGIC)] != MAGIC:
        raise AssetError('The DIET header is invalid.')
    header = image[offset:offset+HEADER]
    packed = (header[9]&15)<<16 | int.from_bytes(header[10:12],'little')
    size = (header[14]>>2)<<16 | int.from_bytes(header[15:17],'little')
    end = offset+HEADER+packed
    if end > len(image) or packed < 2 or not 0 < size <= MAX_OUTPUT:
        raise AssetError('The DIET header has an invalid extent.')
    payload = image[offset+HEADER:end]
    crc = 0
    for index, value in enumerate(payload):
        if not index%4096:
            check()
        crc = (crc>>8)^_CRC[(crc^value)&255]
    if crc != int.from_bytes(header[12:14],'little'):
        raise AssetError('The DIET checksum does not match.')

    source = _Stream(payload)
    out = bytearray()
    next_check = 0
    while True:
        if source.at >= next_check:
            check()
            next_check = source.at+4096
        if source.bit():
            if len(out) == size:
                raise AssetError('The DIET stream exceeds its output size.')
            out.append(source.byte())
            continue
        long = source.bit()
        low = source.byte()
        if long:
            distance, count = source.distance(low),source.length()
        elif source.bit():
            distance, count = 2304-256*source.bits(3)-low,2
        elif low != 255:
            distance, count = 256-low,2
        elif source.bit():
            continue
        else:
            break
        if not 0 < distance <= len(out) or len(out)+count > size:
            raise AssetError('The DIET stream has an invalid copy.')
        for _ in range(count):
            out.append(out[-distance])
    if len(out) != size:
        raise AssetError('The DIET stream does not match its output size.')
    return bytes(out),end


def members(image, *, check=lambda: None):
    end = 0
    for hit in re.finditer(re.escape(MAGIC),image):
        check()
        if hit.start() < end:
            continue
        try:
            data,end = unpack(image,hit.start(),check=check)
        except AssetError:
            continue
        yield hit.start(),end,data
