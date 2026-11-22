"""Textures in level files whose bounded directory and segment bases are known."""
import struct
import zlib

from .. import formats
from . import level_logos

IMAGE = 'level-world-textures'
_BASE = 0x8024b000


def unpack(image, row):
    try:
        stream = zlib.decompressobj(-15)
        data = stream.decompress(image[row['start']:row['end']], formats.MAX_BYTES+1)
    except zlib.error as error:
        raise formats.AssetError('The level stream is damaged.') from error
    if not stream.eof or len(data) > formats.MAX_BYTES:
        raise formats.AssetError('The level stream is incomplete or too large to preview.')
    return data


def textures(data):
    def word(at):
        return struct.unpack_from('>I', data, at)[0]
    if len(data) < 0x90:
        return []
    scene = word(0) - _BASE
    table = word(0x2c) - _BASE
    if not (0 <= scene <= len(data)-0x60 and 0 <= table <= len(data)-4):
        return []
    pool = word(scene+0x5c) - _BASE
    count = word(table)
    if not 0 <= pool < len(data) or not 1 <= count <= 4096 or table+4+4*count > len(data):
        return []
    result, seen = [], set()
    for i in range(count):
        at = word(table+4+4*i) - _BASE
        if not 0 <= at <= len(data)-0x68 or at % 8:
            continue
        commands = [struct.unpack_from('>II', data, at+8*j) for j in range(13)]
        if ([x[0] >> 24 for x in commands] != [0xe7,0xe3,0xfd,0xf5,0xf0,0xf5,0xe6,0xfd,0xf3,0xf5,0xf2,0xe6,0xdf]
                or commands[2][0] != 0xfd100000 or commands[7][0] != 0xfd500000
                or commands[2][1] >> 24 != 3 or commands[7][1] >> 24 != 3):
            continue
        palette = pool + (commands[2][1] & 0xffffff)
        pixels = pool + (commands[7][1] & 0xffffff)
        tile = commands[10][1]
        width, height = ((tile >> 12) & 0xfff)//4+1, (tile & 0xfff)//4+1
        size = (width*height+1)//2
        if (not 1 <= width <= 256 or not 1 <= height <= 256 or not 0 <= palette <= len(data)-32
                or not 0 <= pixels <= len(data)-size or not any(data[palette:palette+32])):
            continue
        key = (palette,pixels,width,height)
        if key in seen:
            continue
        seen.add(key)
        result.append(dict(offset=pixels, format='ci4', width=width, height=height,
                           palette_offset=palette, palette_format='rgba5551-be'))
    return result


def regions(image, *, check=lambda: None, **kwargs):
    found = []
    for row in level_logos.records(image):
        check()
        try:
            data = unpack(image, row)
        except formats.AssetError:
            continue
        items = textures(data)
        if not items:
            continue
        listed = [dict(label=f'Texture {i+1}', width=x['width'], height=x['height'], frames=1, palettes=1,
                       palette_entries=[16], levels=[dict(width=x['width'], height=x['height'], offset=0)],
                       preview_settings=x) for i,x in enumerate(items)]
        found.append(dict(offset=row['start'], size=row['end']-row['start'], kind='image', media='image',
                          layout=IMAGE, confidence='validated', label=row['name']+' level textures',
                          textures=listed, texture_count=len(listed), frames=1,
                          reason='Level pointers and material display lists bound the CI4 pixels and palette.',
                          preview_settings=dict(format='auto', source='rom', offset=row['start'], texture=0)))
    return found


def preview(image, asset, selection):
    row = dict(start=asset['offset'], end=asset['offset']+asset['size'])
    data = unpack(image, row)
    rows = textures(data)
    if not rows:
        raise formats.AssetError('The level texture bank changed. Rescan ROM Explorer.')
    index = formats.integer(selection.get('texture', 0), 'Texture', 0, len(rows)-1)
    result = formats.preview(data, rows[index])
    result['settings'] = dict(asset['preview_settings'], texture=index)
    result['details']['note'] = asset['reason']
    return result
