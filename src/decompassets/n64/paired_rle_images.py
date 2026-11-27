"""RGBA images in paired-address directories with byte-run and backreference coding."""

import re
import struct

from .. import formats

LAYOUT = 'paired-rle-image'
_PIXELS = 320*240*2
# Independent portions of the loader's control-byte dispatch establish the
# meaning of otherwise unmarked directory entries.
_DECODER = (
    bytes.fromhex('925300000c001c3f0240202100409021327000ff2e0200801040001a02402021'),
    bytes.fromhex('2e0200a0104000133262001f305100ff022010213042ffff1040002d02378821'),
)
_PAIR = re.compile(rb'(?=\x00...\x80...)', re.S)


def decode(data):
    """Decode a bounded, single-plane block; unsupported interleaved planes stay raw."""
    if len(data) < 5 or int.from_bytes(data[:4], 'big') != len(data)-1:
        return None
    end, at = len(data)-1, 4
    out = bytearray()
    while at < end:
        control = data[at]
        at += 1
        if control < 0x80:
            if at >= end:
                return None
            length = (control >> 2)+2
            distance = ((control << 8) | data[at]) & 0x3ff
            at += 1
            if not distance or distance > len(out) or len(out)+length > _PIXELS:
                return None
            for _ in range(length):
                out.append(out[-distance])
        elif control < 0xa0:
            length = control & 31
            if at+length > end or len(out)+length > _PIXELS:
                return None
            out.extend(data[at:at+length])
            at += length
        else:
            if control < 0xe0:
                if at >= end:
                    return None
                length, value = (control & 31)+2, data[at]
                at += 1
            elif control < 0xff:
                length, value = (control & 31)+2, 0
            else:
                if at >= end:
                    return None
                length, value = data[at]+2, 0
                at += 1
            if len(out)+length > _PIXELS:
                return None
            out.extend(bytes([value])*length)
    return bytes(out) if at == end and len(out) == _PIXELS else None


def _directories(image, check):
    end = 0
    for match in _PAIR.finditer(image):
        start = match.start()
        if start < end or start % 4:
            continue
        check()
        pointers = []
        at = start
        while at+8 <= len(image) and len(pointers) < 4096:
            first, second = struct.unpack_from('>II', image, at)
            if second != first | 0x80000000 or first >= len(image) or pointers and first <= pointers[-1]:
                break
            pointers.append(first)
            at += 8
        end = at
        if len(pointers) >= 16 and pointers[0] >= at:
            yield pointers


def regions(image, *, check=lambda: None, progress=lambda _: None):
    if not all(image.find(signature) >= 0 for signature in _DECODER):
        return []
    result = []
    for pointers in _directories(image, check):
        for start, end in zip(pointers, pointers[1:]):
            check()
            if not 5 <= end-start <= 0x40000 or int.from_bytes(image[start:start+4], 'big') != end-start-1:
                continue
            decoded = decode(image[start:end])
            if decoded is None or any(not value & 1 for value in decoded[1::2]):
                continue
            result.append(dict(kind='image', offset=start, size=end-start, label='Packed tiled RGBA image',
                               layout=LAYOUT, confidence='validated', width=320, height=240,
                               reason='A paired-address directory and matching loader identify the compressed image; '
                                      'its opaque RGBA16 pixels form 64-pixel tiles drawn bottom-to-top.',
                               preview_settings=dict(format='auto', source='rom', offset=start)))
    return result


def preview(image, asset, selection):
    start, size = asset['offset'], asset['size']
    decoded = decode(image[start:start+size])
    if decoded is None:
        raise formats.AssetError('The packed image changed. Rescan ROM Explorer.')
    raster = bytearray(_PIXELS)
    at = 0
    for tile in range(40):
        height = 32 if tile < 35 else 16
        x = (tile//7 if tile < 35 else tile-35)*64
        y = tile%7*32 if tile < 35 else 224
        for row in range(height):
            source = at+(height-1-row)*128
            dest = ((y+row)*320+x)*2
            raster[dest:dest+128] = decoded[source:source+128]
        at += 64*height*2
    result = formats.preview(raster, dict(format='rgba5551-be', width=320, height=240, offset=0))
    result['details']['note'] = asset['reason']
    result['settings'] = asset['preview_settings']
    return result
