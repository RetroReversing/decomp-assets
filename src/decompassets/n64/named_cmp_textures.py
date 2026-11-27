"""Bounded bitstream-LZ texture banks in named sequential archives."""
import base64
import struct

from .. import formats
from . import bind_textures, named_tim_archives

LAYOUT = 'named-archive-cmp'


class Bits:
    def __init__(self, data):
        self.data = data
        self.at = 0

    def read(self, count):
        if self.at+count > len(self.data)*8:
            raise formats.AssetError('The compressed texture bank ends inside a code.')
        value = 0
        for _ in range(count):
            value = value*2 + ((self.data[self.at//8] >> (7-self.at%8)) & 1)
            self.at += 1
        return value


def unpack(data, expected, check=lambda: None):
    """MSB-first literals and absolute 13-bit ring positions, terminated by a zero position."""
    if not 0 < expected <= formats.MAX_BYTES:
        raise formats.AssetError('The compressed texture bank exceeds its output limit.')
    bits = Bits(data)
    ring = bytearray(8192)
    write = 1
    out = bytearray()
    next_check = 0
    while len(out) < expected:
        if len(out) >= next_check:
            check()
            next_check = len(out)+8192
        if bits.read(1):
            values = (bits.read(8),)
        else:
            source = bits.read(13)
            if not source:
                raise formats.AssetError('The compressed texture bank ended early.')
            count = bits.read(4)+3
            if len(out)+count > expected:
                raise formats.AssetError('The compressed texture bank exceeds its declared size.')
            values = None
        for i in range(len(values) if values else count):
            value = values[i] if values else ring[(source+i)&8191]
            out.append(value)
            ring[write] = value
            write = (write+1)&8191
    if bits.read(1) or bits.read(13):
        raise formats.AssetError('The compressed texture bank lacks its end marker.')
    if any(bits.read(1) for _ in range(len(data)*8-bits.at)):
        raise formats.AssetError('The compressed texture bank has nonzero trailing bits.')
    return bytes(out)


def textures(data, check=lambda: None):
    if len(data) < 8:
        return []
    count = int.from_bytes(data[:4], 'little')
    end = 4+count*4
    if not 1 <= count <= 512 or end > len(data):
        return []
    sizes = list(struct.unpack_from('<'+'I'*count, data, 4))
    if min(sizes) < 20 or sum(sizes) > formats.MAX_BYTES:
        return []
    try:
        decoded = unpack(data[end:], sum(sizes), check)
    except formats.AssetError:
        return []
    result = []
    at = 0
    for size in sizes:
        tim = bind_textures._tim(decoded[at:at+size])
        if not tim:
            return []
        result.append((at, size, tim[1], tim[2]))
        at += size
    return decoded, result


def banks(image, rows, check):
    found = []
    for name, offset, size in rows:
        if not name.lower().endswith('.cmp') or not (result := textures(image[offset:offset+size], check)):
            continue
        found.append((name, offset, size, result[1]))
    # A complete directory plus two independent decoded banks establishes this archive even when it contains no
    # standalone TIMs; otherwise the already validated standalone TIMs supply the independent evidence.
    return found if len(found) >= 2 or sum(name.lower().endswith('.tim') for name, _, _ in rows) >= 2 else []


def regions(image, *, check=lambda: None, **kwargs):
    found = []
    for archive, rows in named_tim_archives.candidates(image, check):
        for name, offset, size, frames in banks(image, rows, check):
            found.append(dict(offset=offset, size=size, kind='image', layout=LAYOUT, confidence='validated',
                              label=name, archive=archive, frames=len(frames), width=frames[0][2], height=frames[0][3],
                              reason='A bounded LZ stream expands into the complete TIM images listed in its size table.',
                              preview_settings=dict(format='auto', source='rom', offset=offset, frame=0)))
    return found


def preview(image, asset, selection):
    rows = named_tim_archives.directory(image, asset['archive'])
    valid = banks(image, rows, lambda: None)
    if not any(offset == asset['offset'] and size == asset['size'] for _, offset, size, _ in valid):
        raise formats.AssetError('The named texture archive changed. Rescan ROM Explorer.')
    result = textures(image[asset['offset']:asset['offset']+asset['size']])
    if not result or len(result[1]) != asset['frames']:
        raise formats.AssetError('The compressed texture bank changed. Rescan ROM Explorer.')
    decoded, frames = result
    frame = formats.integer(selection.get('frame', 0), 'Frame', 0, len(frames)-1)
    offset, size, _, _ = frames[frame]
    tim = bind_textures._tim(decoded[offset:offset+size])
    width, height, pixels = bind_textures._tim_pixels(tim)
    encoded = base64.b64encode(formats._png(width, height, pixels)).decode()
    return dict(media='image', data_url='data:image/png;base64,'+encoded,
                settings=dict(asset['preview_settings'], frame=frame),
                details=dict(width=width, height=height, format=tim[0], frame=frame, note=asset['reason']))
