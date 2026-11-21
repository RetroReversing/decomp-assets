"""Bounded directory of sized and aligned Iguana cartridge members."""

import re
import struct

_START = re.compile(rb'CODE\.BIN\x00\x00\x00\x00')
_TRAILER = bytes.fromhex('ffffffff6d616b65')
_NAME = re.compile(rb'[!-~]{1,120}\x00')
_MAX_MEMBERS = 1024


def _directory(image, start):
    cursor = start
    members = {}
    for _ in range(_MAX_MEMBERS):
        if image[cursor:cursor+8] == _TRAILER:
            payload = cursor+8
            break
        if cursor+8 > len(image):
            return None
        size, = struct.unpack_from('>I', image, cursor)
        field = _NAME.match(image, cursor+4, min(len(image), cursor+125))
        if not field or not size or size%4:
            return None
        name = field[0][:-1].lower()
        aligned = (field.end()+3)&~3
        if name in members or any(image[field.end():aligned]):
            return None
        members[name] = size
        cursor = aligned
    else:
        return None
    if len(members)<4 or image[payload:payload+4] != b'RNC\x01' or payload+18>len(image):
        return None
    packed, = struct.unpack_from('>I', image, payload+8)
    if (packed+21)&~3 != members[b'code.bin']:
        return None
    files = {}
    for name, size in members.items():
        if payload+size > len(image):
            return None
        files[name]=(payload,payload+size)
        payload+=size
    return files


def directories(image, *, check=lambda:None):
    for hit in _START.finditer(image):
        check()
        start = hit.start()-4
        if start>=0 and not start%4 and (result := _directory(image,start)):
            yield result
