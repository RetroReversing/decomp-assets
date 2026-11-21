"""Page-aligned resource directories and length-bounded LZ streams."""

import re
import struct

_DIRECTORY = re.compile(rb'\x00\x00\x20\x08\x00\x00\x04\x00')
_DIRECTORY_SIZE = 0x2008
_LIMIT = 1024 * 1024


def regions(image, check):
    for marker in _DIRECTORY.finditer(image):
        check()
        at = marker.start()
        if at % 0x800 or at + _DIRECTORY_SIZE > len(image):
            continue
        base = at + _DIRECTORY_SIZE
        members = []
        cursor = 0
        for index, (relative, size) in enumerate(struct.iter_unpack('>2I', image[at + 8:base])):
            if (relative, size) == (0xffffffff, 0xffffffff):
                continue
            if relative != cursor or size == 0 or base + relative + size > len(image):
                break
            members.append((index, base + relative, size))
            cursor += size
        else:
            yield at, members


def unpack(data):
    length = int.from_bytes(data[:4], 'big')
    if not 0 < length <= _LIMIT or len(data) < 5:
        return None
    ring = bytearray(1024)
    destination, cursor, mask = 0x3be, 4, 0
    result = bytearray()
    while len(result) < length:
        if not mask:
            if cursor >= len(data):
                return None
            flags = data[cursor]
            cursor += 1
            mask = 1
        if flags & mask:
            if cursor >= len(data):
                return None
            values = (data[cursor],)
            cursor += 1
        else:
            if cursor + 2 > len(data):
                return None
            low, high = data[cursor:cursor + 2]
            source, count = low | ((high & 0xc0) << 2), (high & 0x3f) + 3
            cursor += 2
            if len(result) + count > length:
                return None
            values = (ring[(source + i) & 1023] for i in range(count))
        mask = (mask << 1) & 255
        for value in values:
            result.append(value)
            ring[destination] = value
            destination = (destination + 1) & 1023
    return bytes(result)


def records(data):
    if len(data) < 12 or data[:4] != b'64\x00\x38':
        return []
    count = int.from_bytes(data[4:8], 'big')
    end = 12 + 12 * count
    if not 0 < count <= 512 or end > len(data):
        return []
    rows = []
    for kind, value, offset in struct.iter_unpack('>3I', data[12:end]):
        if not end <= offset < len(data):
            # A metadata record can store a literal word inline.
            if kind != 4 or value:
                return []
            offset = None
        rows.append((kind, value, offset))
    return rows
