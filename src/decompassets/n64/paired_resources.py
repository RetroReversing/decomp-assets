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


def local_segments(data):
    """Identify file-local address spaces from tables of display-list pointers."""
    from . import display_meshes

    # Some resources start with 24-byte records whose first word points to a
    # local display list. A different segment in that list can name a texture
    # loaded separately; it must not be interpreted relative to this file.
    command = re.compile(rb'\xfd...(.)...\xf5.{7}\xe6.{7}\xf3.{7}\xe7.{7}\xf5.{7}\xf2.{7}', re.DOTALL)
    vertex = re.compile(rb'[\x01\x04].......', re.DOTALL)
    found = set()
    for start in range(0, min(len(data)-72, 2048), 4):
        pointers = [int.from_bytes(data[start+i*24:start+i*24+4], 'big') for i in range(3)]
        segment = pointers[0] >> 24
        if not 1 <= segment <= 15 or len(set(pointers)) != 3 or any(pointer >> 24 != segment for pointer in pointers):
            continue
        for pointer in pointers:
            at = pointer & 0xffffff
            if at % 8 or at+8 > len(data) or data[at:at+8] != bytes.fromhex('e700000000000000'):
                break
            end = min(len(data), at+512)
            loads = any(match[1][0] == segment for match in command.finditer(data, at, end))
            if not loads and not any(match.start() % 8 == 0 and data[match.start()+4] == segment
                                     and display_meshes.geometry(data, match.start(), len(data), {segment:0},
                                                                 vertex_end=match.start())
                                     for match in vertex.finditer(data, at, end)):
                break
        else:
            found.add(segment)
    return found


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
