"""Bounded indexed cartridge banks and their length-prefixed raw-deflate stream."""

import struct
import zlib

_MAX_MEMBER = 1024 * 1024
_MAX_TOTAL = 64 * 1024 * 1024


def _chunk(image, offset, end):
    if offset + 6 > end:
        return None
    size = struct.unpack_from('>I', image, offset)[0]
    if not 1 <= size <= _MAX_MEMBER:
        return None
    source = memoryview(image)[offset + 4:min(end, offset + 4 + _MAX_MEMBER)]
    decoder = zlib.decompressobj(-15)
    try:
        raw = decoder.decompress(source, size + 1)
    except zlib.error:
        return None
    consumed = len(source) - len(decoder.unused_data) - len(decoder.unconsumed_tail)
    if not decoder.eof or len(raw) != size or consumed < 2:
        return None
    return offset + 4 + consumed, raw


def _table(image, start, end, *, empty=False):
    if start + 8 > end:
        return None
    size = struct.unpack_from('>I', image, start)[0]
    if not 32 <= size <= 0x4000 or size % 8 or start + size > end:
        return None
    result, previous = [], start + size
    for at in range(start, start + size, 8):
        relative, flags = struct.unpack_from('>II', image, at)
        length = flags & 0x0fffffff
        if not length and empty:
            continue
        offset = start + relative
        if not length or offset < previous or offset + length > end:
            return None
        result.append((offset, offset + length, flags >> 28))
        previous = offset + length
    return result


def catalogs(image, *, check=lambda: None):
    """Find complete two-level bank tables and their preceding sequential stream."""
    limit = len(image)
    for start in range(0, limit - 64, 16):
        if start % 0x10000 == 0:
            check()
        first = struct.unpack_from('>I', image, start)[0]
        if not 64 <= first <= 2048 or first % 8:
            continue
        banks = _table(image, start, limit)
        if not banks or len(banks) < 8:
            continue
        indexed = []
        for begin, end, flags in banks:
            entries = _table(image, begin, end, empty=True) if not flags else None
            if entries:
                indexed.extend(entries)
        if len(indexed) < 32:
            continue
        # A long stream ending at the outer index proves the unrelated-looking
        # deflate entries form a single ordered collection. Its first entry is
        # aligned even though later entries need not be.
        candidate = 0
        while candidate < start - 8:
            if candidate % 0x10000 == 0:
                check()
            pos, entries, expanded = candidate, [], 0
            while (chunk := _chunk(image, pos, start)):
                stop, raw = chunk
                expanded += len(raw)
                if expanded > _MAX_TOTAL or len(entries) >= 20000:
                    break
                entries.append((pos, stop, len(raw)))
                pos = stop
            if len(entries) >= 32 and start - pos < 16 and not any(image[pos:start]):
                yield start, indexed, entries
                break
            candidate = ((pos + 15) & ~15) if len(entries) >= 4 else candidate + 16


TEXTURE = 'rzip-catalog-textures'


def _texture_refs(data, flat):
    """Read indexed texture loads whose matching palette is in the same member."""
    found = []
    for offset in range(0, len(data) - 7, 8):
        command, index = struct.unpack_from('>II', data, offset)
        if command != 0xfd500000 or index >= len(flat):
            continue
        size = flat[index][2]
        if size not in (1056, 2080):
            continue
        tile, palette = None, False
        for at in range(offset + 8, min(len(data) - 7, offset + 0x100), 8):
            word, arg = struct.unpack_from('>II', data, at)
            op = word >> 24
            if word == 0xfd500000 or op in (0xde, 0xdf):
                break
            if op == 0xf5 and (arg >> 24) & 7 != 7 and (word >> 21) & 7 == 2 and (word >> 19) & 3 == 0:
                tile = word
            if word == 0xfd100000 and arg & 0x3fffff == index and arg >> 22 == 2:
                palette = True
        if not tile or not palette:
            continue
        width = ((tile >> 9) & 0x1ff) * 16
        pixels = (size - 32) * 2
        if width in (32, 64) and pixels % width == 0 and pixels // width in (32, 64):
            found.append((index, width, pixels // width))
    return found


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for _, indexed, flat in catalogs(image, check=check):
        references = {}
        for start, end, flags in indexed:
            check()
            if flags & 1:
                chunk = _chunk(image, start, end)
                if not chunk or chunk[0] != end:
                    continue
                data = chunk[1]
            else:
                data = image[start:end]
            for index, width, height in _texture_refs(data, flat):
                references.setdefault(index, set()).add((width, height))
        textures = []
        for index, shapes in sorted(references.items()):
            if len(shapes) != 1:
                continue
            width, height = next(iter(shapes))
            start, end, _ = flat[index]
            textures.append(dict(label=f'CI4 {width}×{height}', offset=start, size=end - start,
                                 width=width, height=height, palettes=1, frames=1,
                                 levels=[dict(width=width, height=height, offset=0)]))
        if textures:
            start, end = flat[0][0], flat[-1][1]
            result.append(dict(offset=start, size=end - start, kind='image', layout=TEXTURE,
                               confidence='validated', label=f'{len(textures)} indexed textures',
                               textures=textures, texture_count=len(textures), frames=1, palettes=1,
                               levels=textures[0]['levels'], preview_settings=dict(source='rom', format='auto', offset=start),
                               reason='Display lists load indexed pixels and their adjacent palettes.'))
    return result


def preview(image, asset, selection):
    from .. import formats

    index = formats.integer(selection.get('texture', 0), 'Texture', 0, len(asset['textures']) - 1)
    item = asset['textures'][index]
    decoded = _chunk(image, item['offset'], item['offset'] + item['size'])
    if not decoded or decoded[0] != item['offset'] + item['size']:
        raise formats.AssetError('The compressed texture changed. Rescan ROM Explorer.')
    raw = decoded[1]
    width, height = item['width'], item['height']
    row = width // 2
    if len(raw) != row * height + 32 or row % 8:
        raise formats.AssetError('The texture dimensions no longer match. Rescan ROM Explorer.')
    # The renderer stores odd rows in TMEM order and uses a bottom-left origin.
    pixels = bytearray(raw[:row * height])
    for y in range(1, height, 2):
        at = y * row
        pixels[at:at + row] = bytes(pixels[at + (x ^ 4)] for x in range(row))
    pixels = b''.join(pixels[y * row:(y + 1) * row] for y in range(height - 1, -1, -1)) + raw[-32:]
    settings = dict(format='ci4', width=width, height=height, offset=0,
                    palette_offset=row * height, palette_format='rgba5551-be')
    result = formats.preview(pixels, settings)
    result['details'].update(texture=index, note=asset['reason'])
    result['settings'] = dict(asset['preview_settings'], texture=index, frame=0, palette=0, mip=0)
    return result
