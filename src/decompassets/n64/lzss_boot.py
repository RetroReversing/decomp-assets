"""Recover a boot executable stored in a bounded ring-buffer LZSS stream."""

_LIMIT = 4 * 1024 * 1024


def decode(source, expected):
    if not 0 < expected <= _LIMIT:
        return None
    ring = bytearray(4096)
    position, at, flags = 0xfee, 0, 0
    output = bytearray()
    try:
        while len(output) < expected:
            flags >>= 1
            if not flags & 0x100:
                flags = source[at] | 0xff00
                at += 1
            if flags & 1:
                values = (source[at],)
                at += 1
            else:
                x, y = source[at], source[at + 1]
                at += 2
                offset, count = x | (y & 0xf0) << 4, (y & 15) + 3
                if len(output) + count > expected:
                    return None
                values = None
            for i in range(1 if values else count):
                value = values[0] if values else ring[(offset + i) & 0xfff]
                output.append(value)
                ring[position] = value
                position = (position + 1) & 0xfff
    except IndexError:
        return None
    return bytes(output) if at == len(source) else None

