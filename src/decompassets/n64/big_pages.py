"""Read a structurally bounded paged archive and its individually packed pages."""

import re
import struct

from .chunked_package_images import _chunk

_PAGE = 8192
_LIMIT = 64 * 1024 * 1024


def archives(image):
    for match in re.finditer(b'BIG\0', image):
        base = match.start() - 4
        if base < 0 or base % 4 or base + 16 > len(image):
            continue
        size = struct.unpack_from('>I', image, base + 8)[0]
        if not _PAGE <= size <= _LIMIT:
            continue
        count = (size + _PAGE - 1) // _PAGE
        table_end = 12 + (count + 1) * 4
        if base + table_end > len(image):
            continue
        entries = struct.unpack_from(f'>{count+1}I', image, base + 12)
        offsets = [word >> 4 for word in entries]
        if (offsets[0] != table_end or base + offsets[-1] > len(image)
                or any(word & 15 not in (0, 1) for word in entries)
                or any(a >= b or b - a > _PAGE * 2 for a, b in zip(offsets, offsets[1:]))):
            continue
        yield base, size, entries


def _page(image, archive, index):
    base, size, entries = archive
    if not 0 <= index < len(entries)-1:
        return None
    start, end = base + (entries[index] >> 4), base + (entries[index+1] >> 4)
    expected = min(_PAGE, size - index * _PAGE)
    if entries[index] & 15:
        value = _chunk(memoryview(image)[start:end])
        if not value:
            return None
        data, used = value
        if end-start-used > 3 or any(x not in (0, 255) for x in image[start+used:end]):
            return None
    else:
        data = image[start:end]
    return data if len(data) == expected else None


def unpack(image, archive, check=lambda: None):
    result = bytearray()
    for index in range(len(archive[2])-1):
        if index % 32 == 0:
            check()
        data = _page(image, archive, index)
        if data is None:
            return None
        result.extend(data)
    return bytes(result)


def extract(image, archive, start, size):
    if start < 0 or size < 0 or start + size > archive[1]:
        return None
    first, last = start // _PAGE, (start + size + _PAGE - 1) // _PAGE
    chunks = []
    for index in range(first, last):
        data = _page(image, archive, index)
        if data is None:
            return None
        chunks.append(data)
    offset = start - first * _PAGE
    return b''.join(chunks)[offset:offset+size]


def physical(archive, start, size):
    first, last = start // _PAGE, (start + size + _PAGE - 1) // _PAGE
    base, _, entries = archive
    return base + (entries[first] >> 4), base + (entries[last] >> 4)
