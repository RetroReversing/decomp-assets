"""Indexed RGBA palette images in self-contained zlib members."""
import re
import struct
import zlib

from .. import formats

LAYOUT = 'zlib-indexed-image'
_MARKER = re.compile(rb'\x78[\x01\x5e\x9c\xda]')
_HEADER = struct.Struct('>IIHHI')


def image_at(image, offset):
    if not _MARKER.match(image, offset):
        return None
    try:
        head = zlib.decompressobj().decompress(image[offset:offset+256], _HEADER.size)
        if len(head) != _HEADER.size:
            return None
        kind, flags, width, height, reserved = _HEADER.unpack(head)
        if kind != 0x80000001 or flags or reserved or not (1 <= width <= 1024 and 1 <= height <= 1024):
            return None
        size = 16 + 1024 + width*height
        source = image[offset:offset+size+0x10000]
        reader = zlib.decompressobj()
        data = reader.decompress(source, size+1)
        if not reader.eof or len(data) != size:
            return None
        return len(source)-len(reader.unused_data), width, height, data
    except zlib.error:
        return None


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for index, match in enumerate(_MARKER.finditer(image)):
        if index % 128 == 0:
            check()
        offset = match.start()
        if offset % 4 or not (found := image_at(image, offset)):
            continue
        size, width, height, _ = found
        result.append(dict(offset=offset, size=size, kind='image', confidence='validated', layout=LAYOUT,
                           label=f'Indexed image {width}×{height}', frames=1, palettes=1,
                           frame_offsets=[0], palette_offsets=[16], palette_entries=[256],
                           levels=[dict(width=width, height=height, offset=1040)],
                           reason='The zlib checksum, image dimensions, palette and pixel count agree.',
                           preview_settings=dict(source='rom', format='ci8', offset=offset,
                                                 width=width, height=height)))
    return result


def preview(image, asset, selection):
    found = image_at(image, asset['offset'])
    if not found or found[0] != asset['size']:
        raise formats.AssetError('The compressed indexed image changed. Rescan ROM Explorer.')
    _, width, height, data = found
    result = formats.preview(data, dict(format='ci8', offset=1040, width=width, height=height,
                                        palette_offset=16, palette_format='rgba8888'))
    result['details'].update(note=asset['reason'])
    result['settings'] = dict(source='rom', format='auto', offset=asset['offset'], frame=0, palette=0, mip=0)
    result['decoded'] = dict(codec='zlib', bytes=len(data), block_offset=asset['offset'])
    return result
