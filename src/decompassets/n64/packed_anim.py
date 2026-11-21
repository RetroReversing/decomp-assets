"""Indexed ANIM frames with RGB palettes and a 4 KiB LZSS ring."""

import re
import struct
from itertools import islice

from .. import formats

LAYOUT = 'packed-anim-frame'
_HEADER = struct.Struct('>I4HBB2s')
_MAGIC = re.compile(rb'ANIM\0\0\0\x01')


def _unpack(source, size, check):
    ring = bytearray(b' '*0xfee+bytes(18))
    written = bytearray(bytes([1])*0xfee+bytes(18))
    cursor, destination = 0, 0xfee
    result = bytearray()
    try:
        while len(result)<size:
            if len(result)%4096 < 18:
                check()
            flags = source[cursor]
            cursor += 1
            for bit in range(8):
                if flags & (1<<bit):
                    value = source[cursor]
                    cursor += 1
                    result.append(value)
                    ring[destination] = value
                    written[destination] = 1
                    destination = (destination+1)&4095
                else:
                    low, high = source[cursor:cursor+2]
                    cursor += 2
                    start = low | ((high&0xf0)<<4)
                    count = min((high&15)+3,size-len(result))
                    for index in range(count):
                        pointer = (start+index)&4095
                        if not written[pointer]:
                            return None
                        value = ring[pointer]
                        result.append(value)
                        ring[destination] = value
                        written[destination] = 1
                        destination = (destination+1)&4095
                if len(result)==size:
                    return result if len(source)-cursor < 4 else None
    except (IndexError, ValueError):
        return None
    return None


def _frame(image, offset, check):
    if offset+_HEADER.size > len(image):
        return None
    length, width, height, _, _, depth, palette, marker = _HEADER.unpack_from(image,offset)
    if (marker != b'LZ' or depth not in (4,8) or palette != 1
            or not 0 < width <= 1024 or not 0 < height <= 1024
            or width*height*depth%8 or not offset+length <= len(image)):
        return None
    rgb = offset+_HEADER.size
    pixels = rgb+3*(1<<depth)
    end = offset+length
    if pixels >= end or length>formats.MAX_BYTES:
        return None
    raw = _unpack(image[pixels:end],width*height*depth//8,check)
    if raw is None:
        return None
    return length, width, height, depth, raw


def frames(image, offset, end, check):
    """Read frames within a declared standalone or archived ANIM extent."""
    header = image[offset:offset+48]
    if len(header)!=48 or not _MAGIC.fullmatch(header[:8]) or any(header[16:]):
        return []
    count, delay = struct.unpack_from('>II',header,8)
    if not 0 < count <= 512 or not 0 < delay <= 240:
        return []
    cursor = offset+48
    results = []
    for index in range(count):
        check()
        if cursor+_HEADER.size > end:
            return []
        length, = struct.unpack_from('>I',image,cursor)
        if cursor+length > end:
            return []
        frame = _frame(image,cursor,check)
        if not frame:
            return []
        length, width, height, _, _ = frame
        results.append(dict(offset=cursor,size=length,kind='image',media='image',layout=LAYOUT,
                            label=f'Packed ANIM frame {index+1}',confidence='validated',
                            reason='The native frame header and LZSS stream agree on the indexed pixel extent.',
                            preview_settings=dict(format='auto',source='rom',offset=cursor,width=width,height=height)))
        cursor += length
    return results


def regions(image, *, check=lambda: None, progress=lambda _: None):
    results = []
    for match in islice(_MAGIC.finditer(image),1024):
        if match.start()%4 == 0:
            results.extend(frames(image,match.start(),len(image),check))
    return results


def preview(image, asset, selection):
    offset = asset['offset']
    frame = _frame(image,offset,lambda: None)
    if not frame or frame[0] != asset['size']:
        raise formats.AssetError('The packed ANIM frame changed. Rescan ROM Explorer.')
    _, width, height, depth, raw = frame
    start = offset+_HEADER.size
    palette = bytearray()
    for red, green, blue in struct.iter_unpack('3B',image[start:start+3*(1<<depth)]):
        rgba = ((red>>3)<<11)|((green>>3)<<6)|((blue>>3)<<1)|bool(red or green or blue)
        palette.extend(rgba.to_bytes(2,'big'))
    pixels = bytes(raw)+palette
    settings = dict(format=f'ci{depth}',width=width,height=height,palette_offset=len(raw),palette_format='rgba5551-be')
    result = formats.preview(pixels,settings)
    result['settings'] = asset['preview_settings']
    return result
