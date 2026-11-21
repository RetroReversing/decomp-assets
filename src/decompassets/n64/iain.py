"""The block-compressed Iain resource container."""

import re
import struct

_HEADER_SIZE = 0x18c
_BLOCK_SIZE = 0x1ffc
_MAGIC = re.compile(b'Iain')


def _unpack_block(raw, limit):
    if len(raw) < 4:
        return None
    if raw[0] == 1:
        return raw[4:] if len(raw) - 4 <= limit else None
    if raw[0] != 0:
        return None
    output = bytearray()
    position = 4
    while position < len(raw):
        if position + 2 >= len(raw):
            return None
        flags = raw[position] | raw[position + 1] << 8
        position += 2
        for bit in range(16):
            if position == len(raw):
                break
            if flags & (1 << bit):
                if position + 2 > len(raw):
                    return None
                high, low = raw[position:position + 2]
                position += 2
                distance = (high & 0xf0) << 4 | low
                length = (high & 15) + 1
                if not 0 < distance <= len(output) or len(output) + length > limit:
                    return None
                for _ in range(length):
                    output.append(output[-distance])
            else:
                if len(output) == limit:
                    return None
                output.append(raw[position])
                position += 1
    return output


def unpack(image, offset, end=None):
    """Return the expanded bytes and container extent after validating all blocks."""
    end = len(image) if end is None else min(end, len(image))
    if not 0 <= offset <= end - _HEADER_SIZE:
        return None
    magic, size, count = struct.unpack_from('>4sII', image, offset)
    if magic != b'Iain' or not 1 <= count <= 64 or not 0 < size <= count * _BLOCK_SIZE:
        return None
    offsets = struct.unpack_from(f'>{count}I', image, offset + 12)
    spans = struct.unpack_from(f'>{count}H', image, offset + 0x10c)
    expected = offset + _HEADER_SIZE
    output = bytearray()
    for relative, span in zip(offsets, spans):
        start = offset + relative
        expected_end = start + 4 + span
        if start != expected or expected_end > end:
            return None
        encoding, length = struct.unpack_from('>HH', image, start)
        if not 0 < length <= span:
            return None
        raw = image[start + 4:start + 4 + length]
        limit = min(_BLOCK_SIZE, size - len(output))
        if encoding == 1:
            block = _unpack_block(raw, limit)
        elif encoding == 0 and length <= limit:
            block = raw
        else:
            return None
        if not block:
            return None
        output.extend(block)
        expected = expected_end
    if len(output) == size:
        return output, expected - offset
    return None


def members(image, check):
    for match in _MAGIC.finditer(image):
        offset = match.start()
        if offset % 4:
            continue
        check()
        if decoded := unpack(image, offset):
            data, size = decoded
            yield offset, size, data
