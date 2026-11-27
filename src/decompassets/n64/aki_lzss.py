"""Bounded LZSS streams in relative indexed resource directories."""


def unpack(source, limit, check=lambda: None):
    if len(source) < 4 or source[0] != 0:
        return None
    size = int.from_bytes(source[:4], 'big')
    if not 8 <= size <= limit:
        return None
    out = bytearray()
    at, command, next_check = 4, 0, 0
    while len(out) < size:
        if len(out) >= next_check:
            check()
            next_check = len(out) + 8192
        command >>= 1
        if command < 2:
            if at >= len(source):return None
            command = source[at] | 0x100
            at += 1
        if command & 1:
            if at >= len(source):return None
            out.append(source[at])
            at += 1
        else:
            if at+2 > len(source):return None
            a, b = source[at:at+2]
            at += 2
            distance = ((a | (b << 4 & 0xf00)) + 18) & 0xfff
            distance -= len(out) & 0xfff
            if distance >= 0:distance -= 0x1000
            pos = len(out)+distance
            length = (b & 15)+3
            if len(out)+length > size:return None
            for _ in range(length):
                out.append(out[pos] if pos >= 0 else 0)
                pos += 1
    return out, at
