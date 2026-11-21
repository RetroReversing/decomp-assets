"""Indexed and direct-color members in the native paged resource archive."""

from .. import formats
from . import paged_lz

LAYOUT = 'paged-lz-texture-bank'
_FORMATS = {18: ('ci4', 4, 16), 21: ('ci8', 8, 256), 25: ('rgba8888', 32, 0)}


def _indices_fit(raw, width, height, bits, count):
    if bits == 8:
        return max(raw) < count
    stride = (width + 1) // 2
    return all((raw[y*stride + x//2] >> (4 if x%2 == 0 else 0) & 15) < count
               for y in range(height) for x in range(width))


def textures(data):
    rows = paged_lz.records(data)
    if not rows:
        return []
    offsets = sorted({offset for _, _, offset in rows if offset is not None} | {len(data)})
    ends = dict(zip(offsets, offsets[1:]))
    found = []
    for index, (kind, dimensions, offset) in enumerate(rows):
        if kind not in _FORMATS:
            continue
        fmt, bits, entries = _FORMATS[kind]
        width, height = dimensions >> 16, dimensions & 0xffff
        if not 0 < width <= 1024 or not 0 < height <= 1024:
            continue
        size = ((width * bits + 7) // 8) * height
        end = offset + size
        if not 0 <= ends[offset] - end <= 7:
            continue
        count = palette = 0
        if entries:
            if index + 1 == len(rows):
                continue
            palette_kind, count, palette = rows[index + 1]
            if (palette_kind != 26 or not 0 < count <= entries or palette != ends[offset]
                    or not 0 <= ends[palette] - (palette + count*2) <= 7
                    or not _indices_fit(data[offset:end], width, height, bits, count)):
                continue
        settings = dict(format=fmt, width=width, height=height, offset=offset)
        found.append(dict(label=f'{fmt.upper()} {width}×{height}', frames=1, palettes=int(bool(entries)),
                          frame_offsets=[0], palette_offsets=[palette] if entries else [],
                          palette_entries=[count] if entries else [],
                          levels=[dict(width=width, height=height, offset=0)], preview_settings=settings,
                          size=size, palette_offset=palette, entries=count))
    return found


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for directory, members in paged_lz.regions(image, check):
        for index, offset, size in members:
            check()
            data = paged_lz.unpack(image[offset:offset + size])
            if data is None or not (items := textures(data)):
                continue
            first = items[0]
            result.append(dict(offset=offset, size=size, kind='image', confidence='validated',
                               layout=LAYOUT, textures=items, texture_count=len(items), directory=directory,
                               label=f'Texture resource {index} · {len(items)} texture(s)',
                               frames=1, palettes=first['palettes'], frame_offsets=[0],
                               palette_offsets=first['palette_offsets'], palette_entries=first['palette_entries'],
                               levels=first['levels'], preview_settings={**first['preview_settings'],
                                                                         'source':'rom','offset':offset},
                               reason='The archive bounds the LZ member and the native texture and palette records.'))
    return result


def preview(image, asset, selection):
    offset, size = asset['offset'], asset['size']
    data = paged_lz.unpack(image[offset:offset + size])
    if data is None or not (items := textures(data)):
        raise formats.AssetError('The archived texture resource changed. Rescan ROM Explorer.')
    index = formats.integer(selection.get('texture', 0), 'Texture', 0, len(items) - 1)
    item = items[index]
    settings = item['preview_settings'].copy()
    if count := item['entries']:
        start = settings['offset']
        raw = data[start:start + item['size']]
        palette = item['palette_offset']
        entries = 16 if settings['format'] == 'ci4' else 256
        data = raw + data[palette:palette + 2*count] + bytes(2*(entries-count))
        settings.update(offset=0, palette_offset=len(raw))
    result = formats.preview(data, settings)
    result['details'].update(texture=index, note=asset['reason'])
    result['settings'] = dict(source='rom', format='auto', offset=offset, texture=index, frame=0, palette=0, mip=0)
    return result
