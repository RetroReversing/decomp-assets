"""Named cartridge members and their length-bounded LZKN64 payloads."""

import re
import struct

from .. import formats

_ROW = struct.Struct('>4I')
# The resident table begins with a raw executable row. Its name pointers
# resolve through the N64 boot segment's cartridge-to-RAM displacement.
_FIRST = re.compile(rb'\x80[\x00-\x07]..\0{4}\0\0\x10\x50', re.DOTALL)
_NAME = re.compile(rb'[A-Za-z0-9_.-]{1,24}\0')


def members(image, check):
    for match in _FIRST.finditer(image, 0, min(len(image), 0x100000)):
        check()
        first = match.start()
        if first < 4 or first%4:
            continue
        count = int.from_bytes(image[first-4:first], 'big')
        end = first + count*_ROW.size
        if not 8 <= count <= 2048 or end > len(image):
            continue
        found = []
        cursor = 0x1050
        for pointer, packed, start, stop in _ROW.iter_unpack(image[first:end]):
            name_at = (pointer & 0xffffff) + 0xc00
            name = _NAME.match(image, name_at, name_at + 25)
            if (not 0x80000400 <= pointer < 0x80080000 or not name or packed not in (0, 1)
                    or not cursor == start <= stop <= len(image) or (start | stop)%16):
                break
            if stop > start:
                found.append((name[0][:-1].decode('ascii'), packed, start, stop))
            cursor = stop
        else:
            yield from found
            return


def unpack(data):
    if len(data) < 5:
        return None
    limit = int.from_bytes(data[:4], 'big') - 1
    if not 4 < limit < len(data):
        return None
    out = bytearray()
    cursor = 4
    while cursor < limit:
        command = data[cursor]
        cursor += 1
        if command < 0x80:
            if cursor > limit:
                return None
            distance = ((command << 8) | data[cursor]) & 1023
            cursor += 1
            if not 0 < distance <= len(out):
                return None
            for _ in range(2 + (command >> 2)):
                out.append(out[-distance])
        elif command < 0xa0:
            count = command & 31
            if cursor+count > limit+1:
                return None
            out.extend(data[cursor:cursor+count])
            cursor += count
        else:
            value, count = 0, 2+(command & 31)
            if command < 0xe0 or command == 0xff:
                if cursor > limit:
                    return None
                operand = data[cursor]
                cursor += 1
                if command == 0xff:
                    count = operand+2
                else:
                    value = operand
            out.extend(bytes([value])*count)
        if len(out) > formats.MAX_BYTES:
            return None
    return bytes(out)
