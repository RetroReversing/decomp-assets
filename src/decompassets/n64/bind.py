"""Read BIND member directories and their bounded PACK LZ streams."""

import re
import struct
from dataclasses import dataclass

from ..formats import AssetError

MAX_OUTPUT = 2*1024*1024
MAX_ARCHIVE_OUTPUT = 32*1024*1024
_HEADER = struct.Struct('<4sII')
_ENTRY = struct.Struct('<32sII')
_NAME = re.compile(rb'[A-Za-z0-9_][A-Za-z0-9_.-]*\.PAK', re.IGNORECASE)


@dataclass(frozen=True)
class Member:
    name: str
    offset: int
    size: int
    unpacked: int


def _members(image, archive):
    if archive+8 > len(image):
        return ()
    count = int.from_bytes(image[archive+4:archive+8], 'little')
    end = archive+8+count*_ENTRY.size
    if not 1 <= count <= 2048 or end > len(image):
        return ()
    members = []
    expanded = 0
    for entry in range(archive+8,end,_ENTRY.size):
        padded_name, relative, size = _ENTRY.unpack_from(image,entry)
        name, _, padding = padded_name.partition(b'\0')
        at = archive+relative
        if (not _NAME.fullmatch(name) or any(padding) or relative%4 or size%4 or size < _HEADER.size
                or at-end not in (0,4) or any(image[end:at]) or at+size > len(image)):
            return ()
        magic, unpacked, packed = _HEADER.unpack_from(image,at)
        extent = _HEADER.size+packed
        if magic != b'PACK' or not 0 < unpacked <= MAX_OUTPUT or not packed or not 3 <= size-extent <= 6:
            return ()
        expanded += unpacked
        if expanded > MAX_ARCHIVE_OUTPUT:
            return ()
        members.append(Member(name.decode('ascii'),at,extent,unpacked))
        end = at+size
    return tuple(members)


def archives(image, *, check=lambda: None):
    """Yield structurally checked directories in cartridge order."""
    end = 0
    for hit in re.finditer(rb'BIND',image):
        check()
        at = hit.start()
        if at%4 or at < end:
            continue
        if members := _members(image,at):
            yield members
            end = members[-1].offset+members[-1].size


class _Input:
    def __init__(self, data, end):
        self.data = data
        self.at = _HEADER.size
        self.end = end
        self.flags = 0
        self.bit_count = 0

    def literal(self, count=1):
        end = self.at+count
        if end > self.end:
            raise AssetError('The PACK stream ended before its declared output.')
        value = self.data[self.at:end]
        self.at = end
        return value

    def bits(self, count=1):
        value = 0
        for _ in range(count):
            if not self.bit_count:
                self.flags = self.literal()[0]
                self.bit_count = 8
            self.bit_count -= 1
            value = (value<<1) | ((self.flags>>self.bit_count)&1)
        return value

    def distance(self):
        high = 0
        if self.bits():
            first = self.bits()
            if self.bits():
                high = 4+2*first+self.bits()
                if not self.bits():
                    high = 2*high+self.bits()
            else:
                high = first or (2+self.bits())
        return (high<<8)+self.literal()[0]+1


def unpack(data, *, check=lambda: None):
    if len(data) < _HEADER.size:
        raise AssetError('The PACK header is truncated.')
    magic, size, packed = _HEADER.unpack_from(data)
    if magic != b'PACK' or not 0 < size <= MAX_OUTPUT or packed != len(data)-_HEADER.size:
        raise AssetError('The PACK header has an invalid extent.')
    source = _Input(data,len(data))
    output = bytearray()
    source.bits(2)
    next_check = source.at
    while True:
        if source.at >= next_check:
            check()
            next_check = source.at+4096
        if not source.bits():
            count, distance = 1, 0
        elif not source.bits():
            first = source.bits()
            count = 6+2*first+source.bits() if source.bits() else 4+first
            if count == 9:
                count, distance = 12+4*source.bits(4), 0
            else:
                distance = source.distance()
        elif not source.bits():
            count, distance = 2, source.literal()[0]+1
        elif not source.bits():
            count, distance = 3, source.distance()
        else:
            count = source.literal()[0]
            if not count:
                source.bits()
                if len(output) == size and source.at == source.end:
                    return bytes(output)
                continue
            count += 8
            distance = source.distance()
        if len(output)+count > size or distance > len(output):
            raise AssetError('The PACK stream contains an invalid copy or output length.')
        if distance:
            for _ in range(count):
                output.append(output[-distance])
        else:
            output.extend(source.literal(count))


def regions(image, *, check=lambda: None, progress=lambda _: None):
    from . import bind_models, bind_textures

    assets = []
    for members in archives(image,check=check):
        screens = len(members) > 1 and all(member.unpacked == bind_textures.SCREEN_SIZE for member in members)
        pairs = bind_textures.sprite_pairs(members)
        for index, member in enumerate(members):
            check()
            if not index%32:
                progress(dict(phase='Reading BIND members',done=index,total=len(members)))
            try:
                data = unpack(image[member.offset:member.offset+member.size],check=check)
            except AssetError:
                continue
            if asset := bind_textures.asset(data,member,screen=screens,pair=pairs.get(member)) or bind_models.asset(data,member):
                assets.append(asset)
    return assets
