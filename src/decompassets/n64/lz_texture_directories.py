"""Offset-indexed LZ archives with named N64 texture and palette records."""

import re
import struct
from itertools import islice

from .. import formats

LAYOUT = 'n64-lz-texture-directory'
_DIRECTORY_END = re.compile(rb'[\x00-\x03]..[\x00\x10\x20\x30\x40\x50\x60\x70\x80\x90\xa0\xb0\xc0\xd0\xe0\xf0]\xff{4}', re.S)
_DIRECTORY = struct.Struct('>128I')
_HEADER = struct.Struct('>10I')
_TEXTURE = struct.Struct('>16s4H2I')
_PALETTE = struct.Struct('>16s2I')
_COMMAND = struct.Struct('>2I')
_NAME = re.compile(rb'[ -~]{1,16}')
_FORMATS = {2: 'ci4', 0x102: 'ci8', 4: 'i4', 0x104: 'i8', 0x105: 'ci8', 0x300: 'rgba8888'}
_BITS = {'ci4': 4, 'ci8': 8, 'i4': 4, 'i8': 8, 'rgba8888': 32}


def unpack(data, check=lambda: None):
    """Read an LSB-first stream with absolute positions in a 4 KiB dictionary."""
    size_limit = formats.MAX_BYTES
    out = bytearray()
    cursor = next_check = 0
    while cursor < len(data) and len(out) < size_limit:
        if len(out) >= next_check:
            check()
            next_check = len(out) + 4096
        flags = data[cursor]
        cursor += 1
        for bit in range(8):
            if flags & (1 << bit):
                if cursor >= len(data) or len(out) >= size_limit:
                    raise formats.AssetError('The LZ asset ends inside a literal or exceeds its size limit.')
                out.append(data[cursor])
                cursor += 1
                continue
            if cursor + 2 > len(data):
                raise formats.AssetError('The LZ asset ends inside a match.')
            code, low = data[cursor:cursor + 2]
            cursor += 2
            source = (code & 240) << 4 | low
            length = (code & 15) + 2
            if not source and length == 2:
                return out, cursor
            distance = ((len(out) - source) & 4095) + 1
            if distance > len(out) or len(out) + length > size_limit:
                raise formats.AssetError('The LZ asset contains an invalid match or exceeds its size limit.')
            for _ in range(length):
                out.append(out[-distance])
    raise formats.AssetError('The LZ asset has no terminator within its input and output limits.')


def _directory(image, check):
    for match in islice(_DIRECTORY_END.finditer(image, 0, min(len(image), 0x200000)), 2048):
        check()
        end = match.start() + 4
        start = end - _DIRECTORY.size
        if start < 0 or start % 4:
            continue
        offsets = sorted(set(_DIRECTORY.unpack_from(image, start)))
        if (len(offsets) != 128 or offsets[0] < end + 4 or offsets[-1] >= len(image)
                or any(offset % 16 for offset in offsets)):
            continue
        yield tuple(zip(offsets, [*offsets[1:], len(image)]))


def layout(data):
    if len(data) < _HEADER.size:
        return None
    models, size, textures, palettes, nm, nt, np, lists, _, _ = _HEADER.unpack_from(data)
    if (not _HEADER.size <= lists <= models <= textures <= palettes <= size <= len(data)
            or textures != models + nm * 52 or palettes != textures + nt * _TEXTURE.size
            or palettes + np * _PALETTE.size > size or max(nm, nt, np) > 4096):
        return None
    return models, textures, palettes, nm, nt, np, lists


def _list_texture(data, start, end, pixel_end, width, height):
    """Validate a local texture list, including strip heights and palette slots."""
    if start + 8 > end or data[start] != 0xfd:
        return None
    address = palette_pointer = None
    palettes, tiles, sizes = [], {}, {}
    for at in range(start, min(end, start + 512) - 7, 8):
        word, value = _COMMAND.unpack_from(data, at)
        op, tile = word >> 24, value >> 24 & 7
        if op == 0xfd:
            if not _HEADER.size <= value < pixel_end:
                return None
            palette_pointer = value
        elif op == 0xf3:
            if address is not None:
                return None
            address = palette_pointer
        elif op == 0xf0:
            entries = (value >> 14 & 1023) + 1
            palettes.append((palette_pointer, entries))
        elif op == 0xf5:
            tiles[tile] = (value >> 20 & 15, word >> 21 & 7, word >> 19 & 3)
        elif op == 0xf2:
            if word & 0xffffff or value & 0x003003:
                return None
            sizes[tile] = (((value >> 14) & 1023) + 1, ((value >> 2) & 1023) + 1)
        elif op == 0xdf and not (word & 0xffffff or value):
            if address is None or not sizes.keys() <= tiles.keys():
                return None
            # Some atlas lists define alternate tile views. Prefer slot zero
            # when it covers the whole descriptor and use strips otherwise.
            if sizes.get(0) == (width, height):
                return address, palettes, [(*tiles[0], height)]
            stripes = [(*tiles[tile], rows) for tile, (columns, rows) in sorted(sizes.items()) if columns == width]
            if stripes and sum(row[3] for row in stripes) == height:
                return address, palettes, stripes
            return None
        elif op not in (0xd7, 0xe6, 0xe7, 0xe8):
            return None
    return None


def _pixel_rows(data, settings, strips, palettes, expected):
    fmt = settings['format']
    actual = {'ci4': (2, 0), 'ci8': (2, 1), 'i4': (4, 0), 'i8': (4, 1), 'rgba8888': (0, 3)}[fmt]
    row_bytes = (settings['width'] * _BITS[fmt] + 7) // 8
    offset = settings['offset']
    result = []
    for slot, kind, size, rows in strips:
        if (kind, size) != actual:
            return None
        palette = expected
        if palettes:
            if slot >= len(palettes) or palettes[slot][1] != (16 if fmt == 'ci4' else 256):
                return None
            palette = palettes[slot][0]
            if palette is None:
                return None
        result.append(dict(settings, height=rows, offset=offset, palette_offset=palette))
        offset += row_bytes * rows
    return result


def textures(data, bank):
    models, start, palette_at, _, count, palette_count, lists = bank
    result = []
    for i in range(count):
        name, width, height, kind, index, offset, _ = _TEXTURE.unpack_from(data, start + i * _TEXTURE.size)
        name = name.rstrip(b'\0 ')
        fmt = _FORMATS.get(kind)
        if (not _NAME.fullmatch(name) or fmt is None
                or not 0 < width <= formats.MAX_DIMENSION or not 0 < height <= formats.MAX_DIMENSION
                or width * height > formats.MAX_PIXELS):
            continue
        palette, entries = None, 0
        required = 16 if fmt == 'ci4' else 256 if fmt == 'ci8' else 0
        if required:
            if index >= palette_count:
                continue
            _, palette_word, palette = _PALETTE.unpack_from(data, palette_at + index * _PALETTE.size)
            entries = (palette_word >> 16) + 1
            if not required <= entries <= 256 or not _HEADER.size <= palette <= lists - entries*2:
                continue
        elif index != 0xffff:
            continue
        settings = dict(format=fmt, width=width, height=height, offset=offset, palette_offset=palette)
        if lists <= offset < models:
            local = _list_texture(data, offset, models, lists, width, height)
            if local is None:
                continue
            offset, palettes, stripes = local
            settings['offset'] = offset
            strips = _pixel_rows(data, settings, stripes, palettes, palette)
            if strips is None:
                continue
        else:
            strips = [settings]
        size = ((width * _BITS[fmt] + 7) // 8) * height
        if not _HEADER.size <= offset <= lists-size:
            continue
        if any(required and (row['palette_offset'] is None or
                             not _HEADER.size <= row['palette_offset'] <= lists - required*2)
               for row in strips):
            continue
        result.append(dict(label=name.decode('ascii'), palettes=int(bool(required)), frames=1,
                           preview_settings=settings, strips=strips))
    return result


def regions(image, *, models=None, check=lambda: None, progress=lambda _: None):
    from . import lz_directory_models
    for directory in _directory(image, check):
        assets, model_assets, valid, decoded = [], [], 0, 0
        for offset, end in directory:
            check()
            if decoded >= 32 * 1024 * 1024:
                break
            try:
                data, used = unpack(image[offset:min(end, offset + formats.MAX_BYTES)], check)
            except formats.AssetError:
                continue
            decoded += len(data)
            if (directory_entry := layout(data)) is None:
                continue
            valid += 1
            if models is not None and (entries := lz_directory_models.meshes(data, directory_entry, check)):
                model_assets.append(lz_directory_models.asset(offset, used, entries))
            if not (items := textures(data, directory_entry)):
                continue
            settings = dict(items[0]['preview_settings'], source='rom', offset=offset)
            assets.append(dict(offset=offset, size=used, kind='image', media='image', layout=LAYOUT,
                               confidence='validated', label='Indexed LZ texture bank', textures=items,
                               frames=1, palettes=items[0]['palettes'], preview_settings=settings,
                               reason='The cartridge directory bounds the LZ stream and its named RDP texture records.'))
        if valid >= 8:
            if models is not None:
                models.extend(model_assets)
            return assets
    return []


def preview(image, asset, selection):
    for key in ('frame', 'mip', 'palette'):
        formats.integer(selection.get(key, 0), key.capitalize(), 0, 0)
    items = asset['textures']
    texture = items[formats.integer(selection.get('texture', 0), 'Texture', 0, len(items)-1)]
    compressed = formats._take(image, asset['offset'], asset['size'])
    data, _ = unpack(compressed)
    settings = texture['preview_settings']
    pixels = b''.join(formats.texture_pixels(data, strip)[0] for strip in texture['strips'])
    result = formats.preview(formats._png(settings['width'], settings['height'], pixels), {'format': 'auto'})
    result['details']['note'] = asset['reason']
    result['settings'] = dict(asset['preview_settings'], width=settings['width'], height=settings['height'],
                              format=settings['format'])
    return result
