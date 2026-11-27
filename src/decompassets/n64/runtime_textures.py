"""Find cartridge textures referenced by captured N64 display lists."""

from .. import formats
from .paired_resource_textures import _COMMAND, _FORMATS, _LOAD

LAYOUT = 'runtime-observed-texture'


def regions(image, snapshots, *, check=lambda: None):
    """Map complete, unambiguous RAM texture loads back to unchanged cartridge bytes.

    Snapshots are big-endian RDRAM. A full load sequence supplies the tile
    format, pitch and dimensions; only direct, uniquely matching ROM bytes are
    reported. Segmented pointers, palettes and runtime-generated data need
    additional evidence and are deliberately left for other recognizers.
    """
    found = {}
    for ram in snapshots:
        for match in _LOAD.finditer(ram):
            check()
            if match.start() % 8:
                continue
            source, load, sync, block, pipe, tile, bounds = _COMMAND.iter_unpack(match[0])
            kind, size = tile[0] >> 21 & 7, tile[0] >> 19 & 3
            fmt = _FORMATS.get((kind, size))
            if (not fmt or kind == 2 or sync != (0xe6000000, 0) or pipe != (0xe7000000, 0)
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
            key = offset, width, height, fmt
            found[key] = dict(offset=offset, size=count, kind='image', layout=LAYOUT, confidence='validated',
                              label=f'{fmt.upper()} {width}×{height} · runtime texture',
                              width=width, height=height, format=fmt,
                              preview_settings=dict(source='rom', format='auto', offset=offset),
                              reason='A runtime display-list load gives this format and size; its complete pixels uniquely match the ROM.')
    return list(found.values())


def preview(image, asset, selection):
    offset, size = asset['offset'], asset['size']
    if offset < 0 or size < 0 or offset + size > len(image):
        raise formats.AssetError('The runtime texture is outside the image. Scan ROM Explorer again.')
    result = formats.preview(image, dict(format=asset['format'], width=asset['width'], height=asset['height'], offset=offset))
    result['details']['note'] = asset['reason']
    result['settings'] = dict(source='rom', format='auto', offset=offset)
    return result
