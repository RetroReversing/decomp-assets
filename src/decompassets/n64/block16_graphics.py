"""Size-prefixed resources with 16-bit control words and bounded LZ/RLE tokens."""
import struct

TEXTURES = 'runtime-block16-textures'
MAX_EXPANDED = 4 * 1024 * 1024
MAX_PACKED = 4 * 1024 * 1024


def descriptors(image, check=lambda: None):
    """Runs of three aligned, size-bounded blocks establish resource framing."""
    found = set()
    seen_starts = set()
    for start in range(0, len(image)-27, 16):
        if not start & 0x3ffff:
            check()
        if start in seen_starts:
            continue
        at = start
        run = []
        while at + 11 <= len(image) and len(run) < 4096:
            expanded, packed = struct.unpack_from('>II', image, at)
            end = at + 8 + packed
            if (not 128 <= expanded <= MAX_EXPANDED or not 3 <= packed <= MAX_PACKED
                    or end > len(image) or image[at+8] not in (0x40, 0x80)):
                break
            next_at = (end+15) & ~15
            if next_at > len(image) or any(image[end:next_at]):
                break
            run.append((at, end))
            at = next_at
        if len(run) >= 3:
            found.update(run)
            seen_starts.update(a for a, _ in run)
    return sorted(found)


def inflate(source, check=lambda: None):
    """Expand exactly one declared block; reject invalid references and lengths."""
    if len(source) < 11:
        return None
    expanded, packed = struct.unpack_from('>II', source)
    if not 0 < expanded <= MAX_EXPANDED or not 3 <= packed <= MAX_PACKED or packed+8 > len(source):
        return None
    data = source[8:8+packed]
    if data[0] == 0x80:
        return (bytes(data[1:]), packed+8) if len(data)-1 == expanded else None
    if data[0] != 0x40:
        return None
    pos, bits, flags = 3, 16, int.from_bytes(data[1:3], 'big')
    output = bytearray()
    next_check = 0
    try:
        while pos < len(data):
            if len(output) >= next_check:
                check()
                next_check = len(output)+8192
            if not bits:
                if pos+2 > len(data):
                    return None
                flags = int.from_bytes(data[pos:pos+2], 'big')
                pos += 2
                bits = 16
            if flags & 0x8000:
                if pos+2 > len(data):
                    return None
                first, second = data[pos], data[pos+1]
                pos += 2
                distance = first*16 + (second >> 4)
                if distance:
                    length = (second & 15)+3
                    if distance > len(output) or len(output)+length > expanded:
                        return None
                    for _ in range(length):
                        output.append(output[-distance])
                else:
                    if pos+2 > len(data):
                        return None
                    length = ((second << 8) | data[pos])+16
                    pos += 1
                    if len(output)+length > expanded:
                        return None
                    output.extend(bytes([data[pos]])*length)
                    pos += 1
            else:
                if len(output) >= expanded:
                    return None
                output.append(data[pos])
                pos += 1
            flags = (flags << 1) & 0xffff
            bits -= 1
    except IndexError:
        return None
    return (bytes(output), packed+8) if len(output) == expanded else None
