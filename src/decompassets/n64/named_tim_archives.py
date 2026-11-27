"""TIM images in sequential archives with fixed-width names and little-endian sizes."""
import base64
import re
import struct

from .. import formats
from . import bind_textures

LAYOUT = 'named-archive-tim'
_NAME = re.compile(rb'[A-Za-z0-9_-]{1,12}\.(?:tim|cmp|prm)\0', re.I)
_SAFE = re.compile(rb'[A-Za-z0-9_-]{1,12}\.[A-Za-z0-9]{1,3}\Z')


def members(image, start):
    if not 0 <= start <= len(image)-2:
        return []
    count = int.from_bytes(image[start:start+2], 'little')
    table = start+2
    end = table+25*count
    if not 2 <= count <= 128 or end > len(image):
        return []
    cursor = end
    images = []
    records = []
    names = set()
    for i in range(count):
        row = image[table+i*25:table+(i+1)*25]
        name = bytes(row[:16]).split(b'\0', 1)[0]
        if not _SAFE.fullmatch(name) or name.lower() in names or b'\0' not in row[:16]:
            return []
        names.add(name.lower())
        unpacked, stored = struct.unpack_from('<II', row, 16)
        if row[24] != 0 or not 0 < stored <= 4*1024*1024 or stored != unpacked or cursor+stored > len(image):
            return []
        if name.lower().endswith(b'.tim'):
            tim = bind_textures._tim(image[cursor:cursor+stored])
            if not tim:
                return []
            images.append((name.decode('ascii'), cursor, stored, tim[1], tim[2]))
        records.append((name.decode('ascii'), cursor, stored))
        cursor += stored
    return records if len(images) >= 2 else []


def archive(image, start):
    images = []
    for name, offset, size in members(image, start):
        if name.lower().endswith('.tim'):
            tim = bind_textures._tim(image[offset:offset+size])
            images.append((name, offset, size, tim[1], tim[2]))
    return images


def archives(image, check):
    seen = set()
    for match in _NAME.finditer(image):
        start = match.start()-2
        if start in seen:
            continue
        seen.add(start)
        check()
        rows = members(image, start)
        if rows:
            yield start, rows


def regions(image, *, check=lambda: None, **kwargs):
    found = []
    for start, rows in archives(image, check):
        for name, offset, size in rows:
            if not name.lower().endswith('.tim'):
                continue
            tim = bind_textures._tim(image[offset:offset+size])
            width, height = tim[1:3]
            found.append(dict(offset=offset, size=size, kind='image', layout=LAYOUT, confidence='validated',
                              label=name, width=width, height=height, archive=start,
                              reason='A complete sequential directory bounds a TIM image with its palette and pixels.',
                              preview_settings=dict(format='auto', source='rom', offset=offset)))
    return found


def preview(image, asset, selection):
    rows = archive(image, asset['archive'])
    member = next((r for r in rows if r[1] == asset['offset'] and r[2] == asset['size']), None)
    if not member:
        raise formats.AssetError('The named texture archive changed. Rescan ROM Explorer.')
    tim = bind_textures._tim(image[member[1]:member[1]+member[2]])
    if not tim:
        raise formats.AssetError('The TIM image changed. Rescan ROM Explorer.')
    width, height, pixels = bind_textures._tim_pixels(tim)
    encoded = base64.b64encode(formats._png(width, height, pixels)).decode()
    return dict(media='image', data_url='data:image/png;base64,'+encoded, settings=asset['preview_settings'],
                details=dict(width=width, height=height, format=tim[0], note=asset['reason']))
