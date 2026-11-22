"""Named nested archives with adaptive-Huffman indexed textures."""

import re
import struct

from .. import formats
from . import lzhuf

TEXTURE = 'wad-indexed-texture'
_HEADER = re.compile(b'\0\0\0\1\0\0\0\1')
_FOLDER = struct.Struct('>20sIII')
_FILE = struct.Struct('>20sIIII')


def _name(raw):
    name, _, _ = raw.partition(b'\0')
    if not name or not all(32 <= c < 127 for c in name):
        return None
    return name.decode('ascii')


def _files(image, base, end):
    if base + 8 > end:
        return None
    count, _ = struct.unpack_from('>II', image, base)
    if not 1 <= count <= 128 or base + 8 + count * _FOLDER.size > end:
        return None
    files = []
    for i in range(count):
        name, offset, total, _ = _FOLDER.unpack_from(image, base + 8 + i * _FOLDER.size)
        if (_name(name) is None or not 0 < total <= 4096 or offset < 8 + count * _FOLDER.size
                or base + offset + total * _FILE.size > end):
            return None
        for j in range(total):
            name, relative, kind, stored, expanded = _FILE.unpack_from(image, base + offset + j * _FILE.size)
            name = _name(name)
            if (name is None or not 0 <= kind <= 255 or not 0 < stored <= expanded <= lzhuf._LIMIT
                    or base + relative < base or base + relative + stored > end):
                return None
            files.append((name, base + relative, kind, stored, expanded))
    return files


def _groups(image, check):
    for match in _HEADER.finditer(image):
        base = match.start()
        check()
        files = _files(image, base, len(image))
        if not files or len(files) < 4 or not any(name.endswith('.WAD') and kind == 4 for name,_,kind,_,_ in files):
            continue
        for name, at, kind, stored, expanded in files:
            if kind != 4 or stored != expanded:
                continue
            nested = _files(image, at, at + stored)
            if nested is not None:
                yield nested


def _members(image, check):
    for group in _groups(image, check):
        yield from group


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result, seen = [], set()
    for name, offset, kind, size, decoded in _members(image, check):
        if not name.endswith('.TEX') or offset in seen or decoded < 528:
            continue
        seen.add(offset)
        source = image[offset:offset + size]
        try:
            head = lzhuf.unpack(source, decoded, check, prefix=16) if size != decoded else source[:16]
        except formats.AssetError:
            continue
        if len(head) != 16:
            continue
        width,height = struct.unpack_from('>II', head)
        if not (1 <= width <= 2048 and 1 <= height <= 2048 and 16 + width * height + 512 == decoded):
            continue
        result.append(dict(offset=offset, size=size, kind='image', media='image', layout=TEXTURE,
                   label=name, confidence='validated', width=width, height=height,
                   reason='Archive extent, texture dimensions and palette size agree.',
                   decoded_size=decoded, texture_count=1, frames=1, palettes=1,
                   preview_settings=dict(source='rom', format='auto', offset=offset,
                                 width=width, height=height, display_format='ci8')))
    return result


def preview(image, asset, selection):
    formats.integer(selection.get('texture', 0), 'Texture', 0, 0)
    source = image[asset['offset']:asset['offset'] + asset['size']]
    decoded = (lzhuf.unpack(source, asset['decoded_size']) if asset['size'] != asset['decoded_size'] else source)
    if len(decoded) < 16 or struct.unpack_from('>II', decoded) != (asset['width'], asset['height']):
        raise formats.AssetError('The texture changed. Rescan ROM Explorer.')
    w,h = asset['width'],asset['height']
    raw,palette = decoded[16:16+w*h],decoded[16+w*h:]
    if len(raw) != w*h or len(palette) != 512:
        raise formats.AssetError('The texture extent changed. Rescan ROM Explorer.')
    colors = formats._rgba(palette, 'rgba5551-be', 256)
    pixels = b''.join(colors[4*i:4*i+4] for i in raw)
    result = formats.preview(pixels, dict(format='rgba8888', width=w, height=h, offset=0))
    result['details'].update(format='CI8', note='Stored palette preview.')
    result['settings'] = dict(format='auto', source='rom', offset=asset['offset'])
    return result
