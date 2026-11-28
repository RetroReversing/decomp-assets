"""Find cartridge textures referenced by captured N64 display lists."""

from .. import formats
from .paired_resource_textures import _COMMAND, _FORMATS, _LOAD, _PALETTE

LAYOUT = 'runtime-observed-texture'


def _indexed_palette(image, ram, start, texture, offset, kind, palette_index):
    """A directly preceding TLUT load, backed by captured and cartridge bytes."""
    at = start - 56
    if at < 0:
        return None
    mode = _COMMAND.unpack_from(ram, at)
    if mode not in ((0xe3001001, 0x8000), (0xe3000e02, 0x8000), (0xe3000e02, 0xc000)):
        return None
    if not _PALETTE.match(ram, at + 8) or _COMMAND.unpack_from(ram, start - 8) != (0xe7000000, 0):
        return None
    _, pointer = _COMMAND.unpack_from(ram, at + 8)
    _, tile = _COMMAND.unpack_from(ram, at + 24)
    _, command = _COMMAND.unpack_from(ram, at + 40)
    if tile >> 24 != command >> 24:
        return None
    entries = 16 if kind == 'ci4' else 256
    first = palette_index * 16 if kind == 'ci4' else 0
    if first + entries > ((command >> 14) & 1023) + 1:
        return None
    if 0x80000000 <= pointer < 0xc0000000:
        pointer &= 0x1fffffff
    size = entries * 2
    pointer += first * 2
    if pointer + size > len(ram):
        return None
    palette = ram[pointer:pointer + size]
    palette_format = 'ia16' if mode[1] == 0xc000 else 'rgba5551-be'
    if not first and pointer + size == texture and offset >= size and palette_format == 'rgba5551-be':
        stored = image[offset - size:offset]
        if stored == palette:
            return offset - size, False, '', palette_format
        if stored == b''.join(palette[i:i + 2][::-1] for i in range(0, size, 2)):
            return offset - size, True, '', palette_format
    # The same colours can occur in several palette tables; their bytes are
    # still observed at the load, even when no one cartridge offset is unique.
    if image.find(palette) >= 0:
        return None, False, bytes(palette).hex(), palette_format
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
            # A 32-bit block loaded with zero DXT is already interleaved for
            # TMEM's odd-line bank swap; reverse that swap for a linear image.
            if fmt == 'rgba8888' and not (block[1] & 0xfff) and stride % 16 == 0:
                asset['odd_row_swap'] = 8
                asset['reason'] += ' Its zero-DXT 32-bit block uses interleaved odd rows.'
            if palette:
                if palette[0] is not None:
                    asset.update(palette_offset=palette[0], palette_little_endian=palette[1])
                    asset['reason'] += ' The adjacent palette matches the runtime TLUT load.'
                else:
                    asset.update(palette=palette[2], palette_format=palette[3])
                    asset['reason'] += ' The captured TLUT colours also occur in the cartridge; their source offset may be ambiguous.'
            found[key] = asset
    from . import runtime_tiled_textures
    return list(found.values()) + runtime_tiled_textures.regions(image, snapshots, check=check)


def preview(image, asset, selection):
    offset, size = asset['offset'], asset['size']
    if offset < 0 or size < 0 or offset + size > len(image):
        raise formats.AssetError('The runtime texture is outside the image. Scan ROM Explorer again.')
    options = dict(format=asset['format'], width=asset['width'], height=asset['height'], offset=offset)
    if asset.get('odd_row_swap') == 8 and asset['format'] == 'rgba8888':
        stride = asset['width'] * 4
        if stride % 16 or size != stride * asset['height']:
            raise formats.AssetError('The runtime texture layout changed. Scan ROM Explorer again.')
        pixels = bytearray(image[offset:offset + size])
        for row in range(1, asset['height'], 2):
            for at in range(row * stride, (row + 1) * stride, 16):
                pixels[at:at + 16] = pixels[at + 8:at + 16] + pixels[at:at + 8]
        result = formats.preview(pixels, dict(options, offset=0))
        result['details']['note'] = asset['reason']
        result['settings'] = dict(source='rom', format='auto', offset=offset)
        return result
    if asset['format'] in ('ci4', 'ci8'):
        if asset.get('palette'):
            try:
                palette = bytes.fromhex(asset['palette'])
            except (TypeError, ValueError):
                raise formats.AssetError('The observed palette is invalid. Scan ROM Explorer again.') from None
            palette_size = 32 if asset['format'] == 'ci4' else 512
            if len(palette) != palette_size or image.find(palette) < 0:
                raise formats.AssetError('The observed palette changed. Scan ROM Explorer again.')
            options['palette_offset'] = len(image)
            options['palette_format'] = asset.get('palette_format', 'rgba5551-be')
            image = bytes(image) + palette
            result = formats.preview(image, options)
            result['details']['note'] = asset['reason']
            result['settings'] = dict(source='rom', format='auto', offset=offset)
            return result
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
