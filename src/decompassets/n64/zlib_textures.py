"""RGBA sprite and texture members with a four-word header inside zlib."""

import re
import struct
import zlib

from .. import formats

LAYOUT = 'zlib-rgba-texture'
_HEADER = struct.Struct('>4I')
_MARKER = re.compile(rb'\x78[\x01\x5e\x9c\xda]')
_MAX_DIMENSION = 1024


def texture(image, offset):
    if not _MARKER.match(image, offset):
        return None
    reader = zlib.decompressobj()
    try:
        head = reader.decompress(image[offset:offset + 256], _HEADER.size)
        if len(head) != _HEADER.size:
            return None
        width, height, depth, visible_width = _HEADER.unpack(head)
        if not (0 < visible_width <= width <= _MAX_DIMENSION
                and 0 < height <= _MAX_DIMENSION and depth in (16, 32)):
            return None
        size = width * height * (depth // 8)
        # Restart with a bound based on the advertised image size, allowing a
        # small overhead for valid zlib streams with incompressible texels.
        source = image[offset:offset + size + 0x10000]
        reader = zlib.decompressobj()
        data = reader.decompress(source, _HEADER.size + size + 1)
    except zlib.error:
        return None
    if not reader.eof or len(data) != _HEADER.size + size:
        return None
    return len(source) - len(reader.unused_data), width, height, depth, visible_width, data


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for index, match in enumerate(_MARKER.finditer(image)):
        if index % 128 == 0:
            check()
        offset = match.start()
        if offset % 4 or not (decoded := texture(image, offset)):
            continue
        size, width, height, depth, visible_width, _ = decoded
        fmt = 'rgba8888' if depth == 32 else 'rgba5551-be'
        result.append(dict(offset=offset, size=size, kind='image', confidence='validated', layout=LAYOUT,
                           label=f'RGBA{depth} texture {width}×{height}', visible_width=visible_width,
                           frames=1, palettes=0, frame_offsets=[0], palette_offsets=[], palette_entries=[],
                           levels=[dict(width=width, height=height, offset=_HEADER.size)],
                           reason='The zlib checksum and the decoded texture dimensions and pixel size agree.',
                           preview_settings=dict(format=fmt, source='rom', offset=offset, width=width, height=height)))
    return result


def preview(image, asset, selection):
    offset = asset['offset']
    decoded = texture(image, offset)
    if decoded is None or decoded[0] != asset['size']:
        raise formats.AssetError('The compressed RGBA texture changed. Rescan ROM Explorer.')
    _, width, height, depth, visible_width, data = decoded
    fmt = 'rgba8888' if depth == 32 else 'rgba5551-be'
    result = formats.preview(data, dict(format=fmt, offset=_HEADER.size, width=width, height=height))
    result['details'].update(visible_width=visible_width, note=asset['reason'])
    result['settings'] = dict(source='rom', format='auto', offset=offset, frame=0, palette=0, mip=0)
    result['decoded'] = dict(codec='zlib', bytes=len(data), block_offset=offset)
    return result
