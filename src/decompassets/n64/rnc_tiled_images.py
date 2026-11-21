"""RNC palette images as CI8 tile grids or banks of CI4 textures."""

import re
import struct

from .. import formats, rnc

LAYOUT = 'rnc-tiled-ci8'
BANK = 'rnc-ci4-bank'
_PIXELS = 0x208
_BANK_HEADER = struct.Struct('>16i')
_BANK_PIXELS = _BANK_HEADER.size+512
_MAGIC = re.compile(rb'RNC[\x01\x02]')


def layout(data):
    if len(data) < _PIXELS:
        return None
    reserved, vertical, horizontal, mode = struct.unpack_from('>IHBB', data)
    if reserved or mode != 3:
        return None
    columns = [min(64, 8 << bit) for bit in range(7, -1, -1) if horizontal & (1 << bit)]
    rows = [min(32, 2 << bit) for bit in range(11, -1, -1) if vertical & (1 << bit)]
    width, height = sum(columns), sum(rows)
    if (not width or not height or (width+63)//64 != (vertical>>12)+1
            or _PIXELS+width*height != len(data)):
        return None
    return columns, rows


def _decode(image, start):
    if start+18 > len(image) or image[start:start+4] not in (b'RNC\1', b'RNC\2'):
        return None
    unpacked, packed = struct.unpack_from('>II', image, start+4)
    end = start+18+packed
    grid_size = _PIXELS < unpacked <= _PIXELS+376*286 and (unpacked-_PIXELS)%16 == 0
    bank_size = _BANK_PIXELS < unpacked <= _BANK_PIXELS+16*2048 and (unpacked-_BANK_PIXELS)%512 == 0
    if not (grid_size or bank_size) or not 0 < packed <= formats.MAX_BYTES or end > len(image):
        return None
    decoder = rnc.unpack if image[start+3] == 1 else rnc.unpack_m2
    try:
        return decoder(image[start:end], max_output=unpacked), end
    except rnc.RncError:
        return None


def _bank(data):
    if len(data) <= _BANK_PIXELS:
        return None
    textures = []
    cursor = _BANK_PIXELS
    for slot, mode in enumerate(_BANK_HEADER.unpack_from(data)):
        if mode in (-1, 3):
            continue  # blank slots have no payload
        if not 4 <= mode <= 7:
            return None
        width, height = 32*(1+(mode&1)), 32*(1+((mode>>1)&1))
        textures.append(dict(
            name=f'Texture slot {slot+1}', width=width, height=height, frames=1, palettes=16,
            preview_settings=dict(format='ci4', width=width, height=height, offset=cursor),
        ))
        cursor += width*height//2
    return textures if cursor == len(data) and textures else None


def regions(image, *, check=lambda: None, progress=lambda _: None):
    assets = []
    for magic in _MAGIC.finditer(image):
        check()
        start = magic.start()
        decoded = _decode(image, start)
        if decoded is None:
            continue
        data, end = decoded
        if grid := layout(data):
            columns, rows = grid
            assets.append(dict(
                kind='image', offset=start, size=end-start, label='RNC tiled image', layout=LAYOUT,
                confidence='validated', width=sum(columns), height=sum(rows),
                reason='The validated RNC output contains a palette and an exact grid of indexed tiles.',
                preview_settings=dict(format='auto', source='rom', offset=start),
            ))
        elif bank := _bank(data):
            assets.append(dict(
                kind='image', offset=start, size=end-start, label='RNC CI4 texture bank', layout=BANK,
                confidence='validated', width=bank[0]['width'], height=bank[0]['height'],
                textures=bank, texture_count=len(bank),
                reason='Every typed slot fits the decoded bank and shares its palette table.',
                preview_settings=dict(format='auto', source='rom', offset=start),
            ))
    return assets


def _raster(data, columns, rows):
    width = sum(columns)
    pixels = bytearray(width*sum(rows))
    cursor = _PIXELS
    y = 0
    for height in rows:
        x = 0
        for tile_width in columns:
            for row in range(y, y+height):
                at = row*width+x
                pixels[at:at+tile_width] = data[cursor:cursor+tile_width]
                cursor += tile_width
            x += tile_width
        y += height
    return data[8:_PIXELS]+pixels


def preview(image, asset, selection):
    decoded = _decode(image, asset['offset'])
    if decoded is None:
        raise formats.AssetError('The compressed image layout changed. Rescan ROM Explorer.')
    data = decoded[0]
    if asset['layout'] == BANK and (textures := _bank(data)):
        texture = formats.integer(selection.get('texture', 0), 'Texture', 0, len(textures)-1)
        palette = formats.integer(selection.get('palette', 0), 'Palette', 0, 15)
        settings = textures[texture]['preview_settings']
        result = formats.preview(data, dict(settings, palette_offset=_BANK_HEADER.size+palette*32))
        result['details'].update(texture=texture, palette=palette, note=asset['reason'])
        result['settings'] = dict(asset['preview_settings'], texture=texture, palette=palette)
        return result
    if asset['layout'] != LAYOUT or not (grid := layout(data)):
        raise formats.AssetError('The compressed image layout changed. Rescan ROM Explorer.')
    columns, rows = grid
    result = formats.preview(_raster(data, columns, rows), dict(
        format='ci8', width=sum(columns), height=sum(rows), palette_offset=0, offset=512,
    ))
    result['details']['note'] = asset['reason']
    result['settings'] = asset['preview_settings']
    return result
