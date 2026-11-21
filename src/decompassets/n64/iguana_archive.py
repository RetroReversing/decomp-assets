"""Bounded directory of sized and aligned Iguana cartridge members."""

import re
import struct
from functools import lru_cache

from .. import rnc

_START = re.compile(rb'CODE\.BIN\x00')
_END = bytes.fromhex('ffffffff')
_NAME = re.compile(rb'[!-~]{1,120}\x00')
_MAX_MEMBERS = 1024


def _directory(image, start, *, aligned):
    cursor = start
    members = []
    for _ in range(_MAX_MEMBERS):
        if image[cursor:cursor+4] == _END:
            payload = cursor+4
            if aligned:
                if image[payload:payload+4] != b'make':
                    return None
                payload += 4
            elif image[payload:payload+4] != b'RNC\x01':
                payload = (payload+3)&~3
            break
        if cursor+8 > len(image):
            return None
        size, = struct.unpack_from('>I', image, cursor)
        field = _NAME.match(image, cursor+4, min(len(image), cursor+125))
        if not field or not size or (aligned and size%4):
            return None
        name = field[0][:-1].lower()
        next_entry = (field.end()+3)&~3 if aligned else field.end()
        if any(image[field.end():next_entry]):
            return None
        members.append((name,size))
        cursor = next_entry
    else:
        return None
    if len(members)<4 or image[payload:payload+4] != b'RNC\x01' or payload+18>len(image):
        return None
    packed, = struct.unpack_from('>I', image, payload+8)
    if members[0] != (b'code.bin',(packed+21)&~3):
        return None
    files = {}
    ambiguous = set()
    for name, size in members:
        if payload+size > len(image):
            return None
        if name in files:
            ambiguous.add(name)
        files[name]=(payload,payload+size)
        payload+=size
    return {name:span for name,span in files.items() if name not in ambiguous}


def directories(image, *, check=lambda:None):
    for hit in _START.finditer(image):
        check()
        start = hit.start()-4
        if start>=0 and not start%4:
            result = _directory(image,start,aligned=True) or _directory(image,start,aligned=False)
            if result:
                yield result


@lru_cache(maxsize=2)
def unpack_program(member):
    # The archive's program member can carry a stale packed CRC. Require the
    # exact expanded length and CRC before using any embedded references.
    size, packed = rnc._method1_header(member, rnc.MAX_OUTPUT)
    data = rnc._method1(member[18:18+packed],size)
    if rnc.crc16(data) != int.from_bytes(member[12:14],'big'):
        raise rnc.RncError('Iguana program output checksum differs')
    return bytes(data)
