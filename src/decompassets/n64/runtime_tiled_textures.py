"""CI8 image rows evidenced by captured F3DEX tiled loads and a runtime TLUT."""
import hashlib
import struct

from .. import formats

LAYOUT = 'runtime-tiled-ci8'


def regions(image, snapshots, *, check=lambda: None):
    """Match complete observed source rows and the TLUT's original prefix to the image."""
    found = {}
    for ram in snapshots:
        palette = None
        candidates = {}
        for at in range(0, len(ram)-80, 8):
            if not at % 0x40000:
                check()
            command, pointer = struct.unpack_from('>II', ram, at)
            if command >> 24 != 0xfd or not 0x80000000 <= pointer < 0x80800000:
                continue
            pointer &= 0x1fffffff
            # A 256-entry RGBA TLUT with the conventional F3DEX load sequence.
            next_commands = [struct.unpack_from('>II', ram, i) for i in range(at+8, at+64, 8)]
            if command & 0xffff0000 == 0xfd100000 and pointer+512 <= len(ram):
                if (any(a >> 24 == 0xf0 and ((b >> 14) & 1023)+1 == 256 for a,b in next_commands)
                        and any(a == 0xba000e02 and b == 0x8000 for a,b in next_commands)):
                    palette = (pointer, at)
                continue
            if command >> 19 & 31 != 9 or palette is None or at-palette[1] > 0x4000:
                continue
            width = (command & 0xfff)+1
            if not 8 <= width <= 512 or width % 8:
                continue
            tile = None
            for i,(a,b) in enumerate(next_commands):
                if a >> 24 == 0xfd:
                    break
                if a >> 24 == 0xf4:
                    left, top = ((a >> 12) & 0xfff)//4, (a & 0xfff)//4
                    right, bottom = ((b >> 12) & 0xfff)//4, (b & 0xfff)//4
                    if (left <= right < width and top <= bottom < 512
                            and any(x >> 24 == 0xf2 for x,_ in next_commands[i+1:])
                            and any(x >> 24 in (0xe4,0xe5) for x,_ in next_commands[i+1:])):
                        tile = (left, top, right, bottom)
                    break
            if tile:
                key = (pointer, palette[0], width)
                old = candidates.get(key)
                candidates[key] = max(tile[3]+1, old or 0)
        for (pointer, pal, width), height in candidates.items():
            check()
            size = width*height
            if size < 128 or pointer+size > len(ram):
                continue
            pixels = bytes(ram[pointer:pointer+size])
            if len(set(pixels)) < 8:
                continue
            offset = image.find(pixels)
            if offset < 0 or image.find(pixels, offset+1) >= 0:
                continue
            colors = bytes(ram[pal:pal+512])
            # Runtime can tint a palette. Its unique unchanged prefix ties it
            # to the image; the actual captured colours are retained for preview.
            anchor = colors[:96]
            if len(set(anchor)) < 8:
                continue
            palette_offset = image.find(anchor)
            if (palette_offset < 0 or image.find(anchor, palette_offset+1) >= 0
                    or not 96 <= offset-palette_offset <= 0x2000):
                continue
            key = (offset, width, height, hashlib.sha256(colors).digest())
            found[key] = dict(offset=offset, size=size, kind='image', media='image', layout=LAYOUT,
                              confidence='validated', label=f'CI8 {width}×{height} · observed rows',
                              width=width, height=height, format='ci8', palette=colors.hex(),
                              palette_offset=palette_offset, frames=1, palettes=1, palette_entries=[256],
                              levels=[dict(width=width, height=height, offset=0)],
                              preview_settings=dict(source='rom', format='auto', offset=offset,
                                                    width=width, height=height),
                              reason='Tiled loads bound these source rows, which uniquely match the image. The captured TLUT shares a unique palette prefix immediately before the pixels; runtime colours may be modified.')
    return list(found.values())


def preview(image, asset, selection):
    offset, size = asset['offset'], asset['size']
    if not 0 <= offset <= len(image)-size or size != asset['width']*asset['height']:
        raise formats.AssetError('The observed texture changed. Scan ROM Explorer again.')
    try:
        palette = bytes.fromhex(asset['palette'])
    except (KeyError, ValueError, TypeError):
        raise formats.AssetError('The observed palette is invalid. Scan ROM Explorer again.') from None
    start = asset['palette_offset']
    if len(palette) != 512 or not 0 <= start <= len(image)-96 or image[start:start+96] != palette[:96]:
        raise formats.AssetError('The observed palette changed. Scan ROM Explorer again.')
    data = bytes(image[offset:offset+size]) + palette
    result = formats.preview(data, dict(format='ci8', width=asset['width'], height=asset['height'],
                                        offset=0, palette_offset=size, palette_format='rgba5551-be'))
    result['details']['note'] = asset['reason']
    result['settings'] = asset['preview_settings']
    return result
