"""Bounded LSB-first ring LZ resources named by cartridge pointer tables."""
import struct

TEXTURES = 'runtime-ring12-textures'
MAX_EXPANDED = 4 * 1024 * 1024


def descriptors(image, check=lambda: None):
    """A run of distinct aligned cartridge addresses establishes an index."""
    found, run = set(), []
    def finish():
        if len(run) >= 4 and len(set(run)) >= 4:
            found.update(run)
        run.clear()
    for index, (value,) in enumerate(struct.iter_unpack('>I', image[:len(image)//4*4])):
        offset = index*4
        if offset % 0x40000 == 0:
            check()
        if 0x1000 <= value < len(image) and not value % 16:
            run.append(value)
            if len(run) >= 4096:
                finish()
        elif run:
            finish()
    finish()
    starts = sorted(found)
    return [(start, end) for start, end in zip(starts, starts[1:]) if 8 < end-start <= 0x200000]


def inflate(source, check=lambda: None):
    """Literal bytes and absolute 12-bit ring references, with a zero-pair terminator."""
    at = flags = remaining = 0
    ring = bytearray(4096)
    write = 1
    out = bytearray()
    next_check = 0
    try:
        while len(out) < MAX_EXPANDED:
            if len(out) >= next_check:
                check()
                next_check = len(out)+8192
            if not remaining:
                flags = source[at]
                at += 1
                remaining = 8
            literal = flags & 1
            flags >>= 1
            remaining -= 1
            if literal:
                value = source[at]
                at += 1
                out.append(value)
                ring[write] = value
                write = (write+1)&4095
                continue
            first, second = source[at], source[at+1]
            at += 2
            index = ((first & 0xf0) << 4) | second
            count = first & 15
            if not index and not count:
                return bytes(out), at
            length = count+2
            if len(out)+length > MAX_EXPANDED:
                return None
            for i in range(length):
                value = ring[(index+i)&4095]
                out.append(value)
                ring[write] = value
                write = (write+1)&4095
    except IndexError:
        pass
    return None
