"""Little-endian size and MSB-first LZ back-references within supplied bounds."""
from .formats import MAX_BYTES, AssetError


def unpack(source):
    if len(source) < 5:
        raise AssetError('The compressed stream is truncated.')
    size = int.from_bytes(source[:4], 'little')
    if not 0 < size <= MAX_BYTES:
        raise AssetError('The expanded size is invalid.')
    output = bytearray()
    pos = 4
    try:
        while len(output) < size:
            flags = source[pos]
            pos += 1
            for bit in range(7, -1, -1):
                if len(output) >= size:
                    break
                value = source[pos]
                pos += 1
                if not (flags >> bit) & 1:
                    output.append(value)
                    continue
                if value < 128:
                    distance, count = value+1, 2
                else:
                    distance = ((value & 15) << 8)+source[pos]+1
                    pos += 1
                    count = ((value & 127) >> 4)+1
                if distance > len(output):
                    raise AssetError('The compressed stream has an invalid back-reference.')
                for _ in range(min(count, size-len(output))):
                    output.append(output[-distance])
    except IndexError:
        raise AssetError('The compressed stream is truncated.') from None
    return bytes(output), pos
