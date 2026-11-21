"""Decode the byte-buffered NRV2B stream used by Borg archives."""

from ..formats import MAX_BYTES, AssetError


def unpack(data, size):
    if not 0 < size <= MAX_BYTES:
        raise AssetError('The Borg member exceeds the expansion limit.')
    out = bytearray()
    cursor = buffer = remaining = 0

    def octet():
        nonlocal cursor
        value = data[cursor]
        cursor += 1
        return value

    def bit():
        nonlocal buffer, remaining
        if not remaining:
            buffer = octet()
            remaining = 8
        remaining -= 1
        return (buffer >> remaining) & 1

    def prefix(limit):
        code = 1
        while True:
            code = (code << 1) | bit()
            if code > limit:
                raise AssetError('The Borg stream contains an oversized match code.')
            if bit():
                return code

    distance = 1
    try:
        while True:
            while bit():
                if len(out) == size:
                    raise AssetError('The Borg stream exceeds its stored output size.')
                out.append(octet())
            code = prefix(0x1000002)
            if code != 2:
                offset = ((code-3) << 8) | octet()
                if offset == 0xffffffff:
                    break
                distance = offset+1
            length = (bit() << 1) | bit()
            if not length:
                length = prefix(size)+2
            length += 1+int(distance > 0xd00)
            if distance > len(out) or length > size-len(out):
                raise AssetError('The Borg stream references bytes outside its output.')
            # Repeating the existing span preserves overlapping LZ copies.
            start = len(out)-distance
            first = out[start:start+min(distance, length)]
            repeated, rest = divmod(length, len(first))
            out.extend(first*repeated+first[:rest])
    except IndexError:
        raise AssetError('The Borg stream ends inside a compression command.') from None
    if len(out) != size:
        raise AssetError('The Borg stream disagrees with its stored output size.')
    return bytes(out)
