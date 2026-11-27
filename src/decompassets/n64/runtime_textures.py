"""Find cartridge textures referenced by captured N64 display lists."""

from .. import formats
from .paired_resource_textures import _COMMAND, _FORMATS, _LOAD, _PALETTE

LAYOUT = 'runtime-observed-texture'


def _indexed_palette(image, ram, start, texture, offset, kind, palette_index):
    """A directly preceding RGBA TLUT and texture, adjacent in both RAM and ROM."""
    at = start - 56
    if at < 0 or _COMMAND.unpack_from(ram, at) != (0xe3001001, 0x8000):
        return None
    if not _PALETTE.match(ram, at + 8) or _COMMAND.unpack_from(ram, start - 8) != (0xe7000000, 0):
        return None
    _, pointer = _COMMAND.unpack_from(ram, at + 8)
    _, command = _COMMAND.unpack_from(ram, at + 40)
    entries = 16 if kind == 'ci4' else 256
    first = palette_index * 16 if kind == 'ci4' else 0
    if first + entries > ((command >> 14) & 1023) + 1:
        return None
    if 0x80000000 <= pointer < 0xc0000000:
        pointer &= 0x1fffffff
    size = entries * 2
    # Restrict this proof to a whole palette immediately before the pixels;
    # a larger TLUT may place the selected bank elsewhere.
    if first or pointer + size != texture or offset < size or pointer + size > len(ram):
        return None
    palette = ram[pointer:pointer + size]
    stored = image[offset - size:offset]
    if stored == palette:
        return offset - size, False
    if stored == b''.join(palette[i:i + 2][::-1] for i in range(0, size, 2)):
        return offset - size, True
    return None


def regions(image, snapshots, *, check=lambda: None):
    """Map complete, unambiguous RAM texture loads back to unchanged cartridge bytes.

    Snapshots are big-endian RDRAM. A full load sequence supplies the tile
    format, pitch and dimensions; only direct, uniquely matching ROM bytes are
    reported. Indexed textures additionally require an adjacent, directly
    loaded RGBA palette proven against the captured RAM and the ROM. Segmented
    pointers and other runtime-generated data need additional evidence.
    """
    snapshots = list(snapshots)
    found = {}
    for ram in snapshots:
        for match in _LOAD.finditer(ram):
            check()
            if match.start() % 8:
                continue
            source, load, sync, block, pipe, tile, bounds = _COMMAND.iter_unpack(match[0])
            kind, size = tile[0] >> 21 & 7, tile[0] >> 19 & 3
            fmt = _FORMATS.get((kind, size))
            if (not fmt or sync != (0xe6000000, 0) or pipe != (0xe7000000, 0)
                    or bounds[0] != 0xf2000000 or bounds[1] & 0x003003
                    or tile[1] >> 24 != bounds[1] >> 24
                    or load[1] >> 24 != block[1] >> 24
                    or (source[0] & 0x00f80000) != (load[0] & 0x00f80000)):
                continue
            width, height = ((bounds[1] >> 14) & 1023) + 1, ((bounds[1] >> 2) & 1023) + 1
            stride = (width * (4 << size) + 7) // 8
            if (tile[0] >> 9 & 511) * 8 != (stride // 2 if size == 3 else stride):
                continue
            count = stride * height
            load_bits = 4 << (load[0] >> 19 & 3)
            if not 128 <= count <= 65536 or ((block[1] >> 12 & 0xfff) + 1) * load_bits < count * 8:
                continue
            pointer = source[1]
            if pointer >= 0x80000000 and pointer < 0xc0000000:
                pointer &= 0x1fffffff
            if pointer + count > len(ram):
                continue
            pixels = bytes(ram[pointer:pointer+count])
            if len(set(pixels)) < 4:
                continue
            offset = image.find(pixels)
            if offset < 0 or image.find(pixels, offset + 1) >= 0:
                continue
            palette = _indexed_palette(image, ram, match.start(), pointer, offset, fmt, (tile[1] >> 20) & 15) if kind == 2 else None
            if kind == 2 and palette is None:
                continue
            key = offset, width, height, fmt, palette
            asset = dict(offset=offset, size=count, kind='image', layout=LAYOUT, confidence='validated',
                              label=f'{fmt.upper()} {width}×{height} · runtime texture',
                              width=width, height=height, format=fmt,
                              preview_settings=dict(source='rom', format='auto', offset=offset),
                              reason='A runtime display-list load gives this format and size; its complete pixels uniquely match the ROM.')
            if palette:
                asset.update(palette_offset=palette[0], palette_little_endian=palette[1])
                asset['reason'] += ' The adjacent palette matches the runtime TLUT load.'
            found[key] = asset
    from . import runtime_tiled_textures
    return list(found.values()) + runtime_tiled_textures.regions(image, snapshots, check=check)


def preview(image, asset, selection):
    offset, size = asset['offset'], asset['size']
    if offset < 0 or size < 0 or offset + size > len(image):
        raise formats.AssetError('The runtime texture is outside the image. Scan ROM Explorer again.')
    options = dict(format=asset['format'], width=asset['width'], height=asset['height'], offset=offset)
    if asset['format'] in ('ci4', 'ci8'):
        palette_offset = asset.get('palette_offset', -1)
        palette_size = 32 if asset['format'] == 'ci4' else 512
        if palette_offset < 0 or palette_offset + palette_size > len(image):
            raise formats.AssetError('The runtime texture palette is outside the image. Scan ROM Explorer again.')
        palette = image[palette_offset:palette_offset + palette_size]
        if asset.get('palette_little_endian'):
            palette = b''.join(palette[i:i + 2][::-1] for i in range(0, palette_size, 2))
        options['palette_offset'] = len(image)
        image = bytes(image) + palette
    result = formats.preview(image, options)
    result['details']['note'] = asset['reason']
    result['settings'] = dict(source='rom', format='auto', offset=offset)
    return result
