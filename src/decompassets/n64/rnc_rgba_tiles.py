"""RGBA16 tile grids with separate intensity planes inside RNC members."""
import re
import struct

from .. import formats, rnc

LAYOUT = 'rnc-rgba-tile-grid'
_TILE = 32
_COLOR_BYTES = _TILE*_TILE*2
_MASK_BYTES = _TILE*_TILE//2
_STRIDE = _COLOR_BYTES+_MASK_BYTES+8
_LIMIT = 1024*1024


def image_at(image, offset):
    if offset < 0 or image[offset:offset+4] != b'RNC\x01' or offset+18 > len(image):
        return None
    expanded, packed = struct.unpack_from('>II', image, offset+4)
    size = 18+packed
    if not 16 < expanded <= _LIMIT or not packed or offset+size > len(image):
        return None
    try:
        data = rnc.unpack(image[offset:offset+size], max_output=_LIMIT)
        cols, rows, width, height, tile_width, tile_height = struct.unpack_from('>4H2I', data)
    except (rnc.RncError, struct.error):
        return None
    if (not 1 <= cols <= 16 or not 1 <= rows <= 16 or (width, height) != (cols*_TILE, rows*_TILE)
            or (tile_width, tile_height) != (_TILE, _TILE)):
        return None
    count = cols*rows
    if len(data) != 16+count*(_COLOR_BYTES+_MASK_BYTES)+(count-1)*8:
        return None
    if any(data[16+i*_STRIDE-8:16+i*_STRIDE] != struct.pack('>II', _TILE, _TILE)
           for i in range(1, count)):
        return None
    return size, cols, rows, data


def regions(image, *, check=lambda: None, progress=lambda _: None):
    found = []
    for index, match in enumerate(re.finditer(b'RNC\x01', image)):
        if index % 32 == 0:
            check()
        offset = match.start()
        if offset % 4 or not (result := image_at(image, offset)):
            continue
        size, cols, rows, _ = result
        width, height = cols*_TILE, rows*_TILE
        found.append(dict(offset=offset, size=size, kind='image', layout=LAYOUT, confidence='validated',
                          label=f'RNC RGBA tile grid {width}×{height}', width=width, height=height,
                          frames=1, palettes=0, frame_offsets=[0], palette_offsets=[], palette_entries=[],
                          levels=[dict(width=width, height=height, offset=16)],
                          reason='The RNC checksums, tile dimensions and grid extents agree. Separate intensity planes are not applied.',
                          preview_settings=dict(source='rom', format='rgba5551-be', offset=offset,
                                                width=width, height=height)))
    return found


def preview(image, asset, selection):
    found = image_at(image, asset['offset'])
    if not found or found[0] != asset['size']:
        raise formats.AssetError('The compressed tile grid changed. Scan ROM Explorer again.')
    _, cols, rows, data = found
    width, height = cols*_TILE, rows*_TILE
    raster = bytearray(width*height*2)
    for tile in range(cols*rows):
        x, y = tile % cols, tile // cols
        start = 16+tile*_STRIDE
        for row in range(_TILE):
            target = ((y*_TILE+row)*width+x*_TILE)*2
            raster[target:target+_TILE*2] = data[start+row*_TILE*2:start+(row+1)*_TILE*2]
    result = formats.preview(raster, dict(format='rgba5551-be', width=width, height=height))
    result['details']['note'] = asset['reason']
    result['settings'] = dict(source='rom', format='auto', offset=asset['offset'], frame=0, palette=0, mip=0)
    result['decoded'] = dict(codec='RNC method 1', bytes=len(data), block_offset=asset['offset'])
    return result
