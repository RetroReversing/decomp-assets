"""Cartridge directories that store each resource offset with its mapped address."""

import re
import struct
import zlib

_PAIR = struct.Struct('>2I')
_CANDIDATE = re.compile(rb'\x00(...)\x80\1', re.DOTALL)
_LIMIT = 4 * 1024 * 1024
_ZLIB_HEADER = re.compile(rb"\x80[\x00-\x3f]..\x78[\x01\x5e\x9c\xda]", re.DOTALL)


def unpack(image, offset, size):
    """Decode one size-prefixed sequence of literals, repeats, and history copies."""
    if not 4 < size <= _LIMIT or not 0 <= offset <= len(image) - size:
        return None
    if int.from_bytes(image[offset:offset + 4], 'big') != size:
        return None
    position, end = offset + 4, offset + size
    output = bytearray()
    while position < end:
        command = image[position]
        position += 1
        if command < 0x80:
            if position == end:
                return None
            distance = (command & 3) << 8 | image[position]
            position += 1
            count = (command >> 2) + 2
            if not 0 < distance <= len(output) or len(output) + count > _LIMIT:
                return None
            for _ in range(count):
                output.append(output[-distance])
        elif command < 0xa0:
            count = command & 31
            if position + count > end or len(output) + count > _LIMIT:
                return None
            output.extend(image[position:position + count])
            position += count
        else:
            count, value = (command & 31) + 2, 0
            if command < 0xe0 or command == 0xff:
                if position == end:
                    return None
                if command == 0xff:
                    count = image[position] + 2
                else:
                    value = image[position]
                position += 1
            if len(output) + count > _LIMIT:
                return None
            output.extend(bytes([value]) * count)
    return output or None



def unpack_zlib(image, offset, size):
    """Check a flagged length prefix and decode only the declared zlib stream."""
    if not 0 <= offset <= len(image) - size or not 10 <= size <= _LIMIT:
        return None
    header, = struct.unpack_from('>I', image, offset)
    if header != 0x80000000 | size:
        return None
    decoder = zlib.decompressobj()
    try:
        data = decoder.decompress(image[offset + 4:offset + size], _LIMIT + 1)
    except zlib.error:
        return None
    if data and len(data) <= _LIMIT and decoder.eof and not decoder.unused_data:
        return data


def unpack_asset(image, asset):
    decode = unpack_zlib if asset.get('codec') == 'zlib' else unpack
    return decode(image, asset['offset'], asset['size'])


def directories(image, check):
    """Yield members bounded by consecutive entries, independently of contents."""
    skipped_until = 0
    for match in _CANDIDATE.finditer(image, 0, min(len(image), 0x100000)):
        start = match.start()
        if start < skipped_until or start % 4:
            continue
        check()
        entries = []
        position = start
        while position + _PAIR.size <= len(image) and len(entries) <= 1024:
            offset, address = _PAIR.unpack_from(image, position)
            if (not position < offset <= len(image) or offset % 2 or address != offset | 0x80000000
                    or entries and offset <= entries[-1]):
                break
            entries.append(offset)
            position += _PAIR.size
        skipped_until = position
        if not 9 <= len(entries) <= 1024 or entries[0] < position:
            continue
        members = []
        for offset, end in zip(entries, entries[1:]):
            size = int.from_bytes(image[offset:offset + 4], 'big')
            if not 4 < size <= _LIMIT or (size + 1) & ~1 != end - offset:
                break
            members.append((offset, size))
        else:
            yield start, members


def regions(image, *, check=lambda: None, progress=lambda _: None):
    from . import paired_resource_models, paired_resource_textures

    result = []
    for directory, members in directories(image, check):
        for index, (offset, size) in enumerate(members, 1):
            check()
            decoded = unpack(image, offset, size)
            if not decoded:
                continue
            if items := paired_resource_textures.textures(decoded):
                result.append(paired_resource_textures.asset(offset, size, directory, index, items))
            if entries := paired_resource_models.meshes(decoded):
                result.append(paired_resource_models.asset(offset, size, directory, entries))
    for index, match in enumerate(_ZLIB_HEADER.finditer(image)):
        if index % 128 == 0:
            check()
        offset = match.start()
        if offset % 2:
            continue
        size = struct.unpack_from('>I', image, offset)[0] & 0x7fffffff
        if not (decoded := unpack_zlib(image, offset, size)):
            continue
        if items := paired_resource_textures.textures(decoded):
            result.append(paired_resource_textures.asset(offset, size, None, f"at 0x{offset:X}", items) | {'codec': 'zlib'})
        if entries := paired_resource_models.meshes(decoded):
            result.append(paired_resource_models.asset(offset, size, None, entries) | {'codec': 'zlib'})
    return result
