"""Read bounded texture loads from an already validated N64 display list."""

import struct

_COMMAND = struct.Struct('>II')
_PIXEL_FORMATS = {(0, 2): 'rgba5551-be', (0, 3): 'rgba8888', (2, 0): 'ci4', (2, 1): 'ci8'}


def _address(pointer, segments, floor, end, size):
    base = segments.get(pointer >> 24)
    if base is None:
        return None
    address = base + (pointer & 0xffffff)
    if floor <= address <= end-size:
        return address
    return None


def textures(data, start, end, segments, *, floor, tlut_command):
    # The load commands use a temporary tile. The render tile declares the
    # actual texel format, row pitch and bounds.
    tiles = {}
    pointer = palette = image = None
    tlut = 0
    for word, value in _COMMAND.iter_unpack(data[start:end]):
        operation, slot = word >> 24, (value >> 24) & 7
        if word == tlut_command:
            tlut = (value >> 14) & 3
        elif operation == 0xfd:
            pointer = value
        elif operation == 0xf5:
            tiles[slot] = ((word >> 21) & 7, (word >> 19) & 3, (word >> 9) & 511)
        elif operation == 0xf0 and pointer is not None:
            entries = ((value >> 14) & 1023) + 1
            palette = _address(pointer, segments, floor, start, entries*2), entries
        elif operation == 0xf3:
            image = pointer
        elif operation == 0xf2 and image is not None and slot in tiles:
            kind, size, pitch = tiles[slot]
            fmt = _PIXEL_FORMATS.get((kind, size))
            if fmt is None or word & 0xffffff or value & 0x003003:
                continue
            width, height = ((value >> 14) & 1023) + 1, ((value >> 2) & 1023) + 1
            stride = (width * (4 << size) + 7)//8
            if pitch*8 != (stride//2 if size == 3 else stride):
                continue
            offset = _address(image, segments, floor, start, stride*height)
            if offset is None:
                continue
            settings = dict(format=fmt, width=width, height=height, offset=offset)
            if kind == 2:
                if tlut not in (2, 3) or not palette or palette[0] is None or palette[1] != (16 if size == 0 else 256):
                    continue
                settings.update(palette_offset=palette[0], palette_format='ia16' if tlut == 3 else 'rgba5551-be')
            yield settings


