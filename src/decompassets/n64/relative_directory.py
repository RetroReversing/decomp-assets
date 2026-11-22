"""Bounded resource tables with offsets relative to a shared directory header."""

import struct
import zlib

_HEADER = struct.Struct('>64I')
_FLAG = 0x80000000
_LIMIT = 4 * 1024 * 1024


def tables(image, *, check=lambda: None):
    """Find a complete 32-table directory; reject malformed or coincidental pointers."""
    position = 0
    while (base := image.find(b'\x00\x00\x01\x00', position)) >= 0:
        position = base + 1
        if base % 4 or base + _HEADER.size > len(image):
            continue
        check()
        words = _HEADER.unpack_from(image, base)
        offsets, counts = words[:32], words[32:]
        if sum(bool(n) for n in counts) < 8:
            continue
        if any((not n) != (not off) or n > 16384 or
               (n and (off < _HEADER.size or base + off + (n + 1) * 4 > len(image)))
               for off, n in zip(offsets, counts)):
            continue
        active = [off for off in offsets if off]
        if any(a >= b for a, b in zip(active, active[1:])):
            continue
        result = []
        valid = True
        for off, n in zip(offsets, counts):
            if not n:
                result.append(())
                continue
            values = struct.unpack_from(f'>{n + 1}I', image, base + off)
            ends = [v & ~_FLAG for v in values]
            if any(x > len(image) - base for x in ends) or any(a > b for a, b in zip(ends, ends[1:])):
                valid = False
                break
            result.append(values)
        if not valid:
            continue
        # Distinct, independently checksummed streams confirm this is a resource
        # directory, rather than a chance sequence of bounded integers.
        confirmed = 0
        for entries in result:
            for a, b in zip(entries, entries[1:]):
                start, end = base + (a & ~_FLAG), base + (b & ~_FLAG)
                if a & _FLAG or end <= start or image[start:start + 3] != b'\x1f\x8b\x08':
                    continue
                if unpack(image, start, end):
                    confirmed += 1
                    if confirmed >= 3:
                        yield base, tuple(result)
                        break
            if confirmed >= 3:
                break


def unpack(image, start, end):
    """Inflate one checksum-verified gzip resource without crossing its entry."""
    if not 0 <= start < end <= len(image):
        return None
    decoder = zlib.decompressobj(31)
    try:
        data = decoder.decompress(image[start:end], _LIMIT + 1)
    except zlib.error:
        return None
    if data and len(data) <= _LIMIT and decoder.eof:
        return data
    return None
