"""Indexed sprite records with little-endian 15-bit palettes in RNC streams."""
import base64
import re
import struct

from .. import formats, rnc

LAYOUT = 'rnc-indexed-sprite-bank'


def frames(data):
    def header(at):
        if at+32 > len(data):
            return None
        width, height, flags = struct.unpack_from('<3H', data, at)
        if (not 1 <= width <= 512 or not 1 <= height <= 512 or width*height % 2
                or flags & ~0x303 or flags & 0x300 not in (0, 0x100, 0x300)
                or any(data[at+6:at+32])):
            return None
        return width, height, flags

    out = []
    at = records = 0
    while at < len(data):
        head = header(at)
        if head is None or records >= 8192:
            return []
        width, height, flags = head
        records += 1
        if at+32 == len(data) or header(at+32):
            at += 32
            continue
        pixels = width*height
        size = 32+pixels//2 if flags & 0x300 == 0 else pixels
        if at+32+size > len(data):
            return []
        if not flags & 0x300:
            palette = at+32
            if len(set(struct.unpack_from('<16H', data, palette))) >= 4:
                out.append((width, height, palette, palette+32))
        at += 32+size
    return out if at == len(data) and records >= 2 else []


def regions(image, *, check=lambda: None, **kwargs):
    result = []
    for match in re.finditer(b'RNC\x01', image):
        at = match.start()
        check()
        try:
            data, size = rnc.unpack_at(image, at)
        except rnc.RncError:
            continue
        images = frames(data)
        if not images:
            continue
        result.append(dict(offset=at, size=size, kind='image', media='image', layout=LAYOUT,
                           label=f'RNC indexed sprite bank ({len(images)} images)', confidence='inferred',
                           frames=len(images), width=images[0][0], height=images[0][1],
                           reason='Bounded records contain indexed pixels and 15-bit palettes; color and nibble order are inferred.',
                           preview_settings=dict(format='auto', source='rom', offset=at, frame=0)))
    return result


def preview(image, asset, selection):
    try:
        data, _ = rnc.unpack_at(image, asset['offset'])
    except rnc.RncError as error:
        raise formats.AssetError('The compressed sprite bank changed. Rescan ROM Explorer.') from error
    images = frames(data)
    if not images:
        raise formats.AssetError('The sprite bank changed. Rescan ROM Explorer.')
    index = formats.integer(selection.get('frame', 0), 'Frame', 0, len(images)-1)
    width, height, palette, start = images[index]
    colors = struct.unpack_from('<16H', data, palette)
    rgba = bytearray()
    for value in data[start:start+width*height//2]:
        for pixel in (value & 15, value >> 4):
            color = colors[pixel]
            rgba.extend(((color & 31)*255//31, ((color >> 5)&31)*255//31,
                         ((color >> 10)&31)*255//31, 255 if color else 0))
    png = formats._png(width, height, rgba)
    return dict(media='image', mime='image/png', data_url='data:image/png;base64,'+base64.b64encode(png).decode(),
                details=dict(width=width, height=height, format='Indexed 4-bit sprite', note=asset['reason']),
                settings=dict(asset['preview_settings'], frame=index))
