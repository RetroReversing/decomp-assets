"""Bounded LZ stream with interleaved two-bit control fields."""
from .formats import MAX_BYTES, AssetError


def unpack(source):
    if len(source) < 4:
        raise AssetError('The LZ stream has no expanded-size header.')
    size = int.from_bytes(source[:4], 'big')
    if not 0 < size <= MAX_BYTES:
        raise AssetError('The LZ expanded size is invalid.')
    output = bytearray()
    pos, bits, remaining = 4, 0, 0

    def byte():
        nonlocal pos
        if pos >= len(source):
            raise AssetError('The LZ stream is truncated.')
        value = source[pos]
        pos += 1
        return value

    def two():
        nonlocal bits, remaining
        if not remaining:
            bits, remaining = byte(), 4
        value = bits & 3
        bits >>= 2
        remaining -= 1
        return value

    skip_literals = False
    while len(output) < size:
        q = two() if not skip_literals else -1
        if q < 0:
            count = 0
        elif q == 0:
            count = 0
            while (value := byte()) == 0:
                count += 255
                if count > size:
                    raise AssetError('The LZ literal run exceeds its output.')
            count += value+1
        elif q == 3:
            count = two()+3
            if count == 6:
                count = two()+6
        else:
            count = q
        if pos+count > len(source) or len(output)+count > size:
            raise AssetError('The LZ literal run is truncated or exceeds its output.')
        output.extend(source[pos:pos+count])
        pos += count
        if len(output) == size:
            break
        command = byte()
        skip_literals = bool(command & 0x80)
        kind = command & 0x60
        if kind == 0:
            distance = (command & 31) | (two() << 5) | (two() << 7)
            count = 2
        elif kind == 0x20:
            distance = (command & 31) | (two() << 5) | (two() << 7)
            value = two()
            distance |= (value & 1) << 9
            count = (value >> 1)+3
        elif kind == 0x40:
            distance = (command & 31) | (two() << 5) | (two() << 7)
            count = two()+5
        else:
            subtype = command & 0x78
            if subtype == 0x60:
                distance = (command & 7) | (byte() << 3) | (two() << 11)
                value = two()
                distance |= (value & 1) << 13
                count = (value >> 1)+3
            elif subtype == 0x68:
                distance = (command & 7) | (byte() << 3) | (two() << 11)
                count = two()+5
            elif subtype == 0x70:
                distance = (command & 7) | (byte() << 3)
                count = (two() | (two() << 2))+9
            elif command & 0x7e in (0x78, 0x7a, 0x7c):
                a, b = byte(), byte()
                subtype = command & 0x7e
                mask, shift, base = {0x78: (63, 6, 4), 0x7a: (31, 5, 8), 0x7c: (7, 3, 16)}[subtype]
                distance = (command & 1) | (a << 1) | ((b & mask) << 9)
                count = (b >> shift)+base
                if subtype == 0x7a:
                    distance += 0x800
            elif command & 1:
                a, b = byte(), byte()
                distance = (a & 127) | (b << 7)
                count = byte()
                if not a & 128:
                    count |= two() << 8
                    count |= two() << 10
                count += 5
            else:
                distance, a = byte(), byte()
                distance |= (a & 7) << 8
                count = (a >> 3) | (two() << 5)
                count += 25
        distance += 1
        if distance > len(output):
            raise AssetError('The LZ stream has an invalid back-reference.')
        # The original loader copies a whole last match, even if it passes the
        # declared extent; only the declared bytes belong to this resource.
        for _ in range(min(count, size-len(output))):
            output.append(output[-distance])
    return bytes(output), pos
