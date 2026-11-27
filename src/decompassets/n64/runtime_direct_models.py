"""Local non-planar meshes with cartridge-backed runtime vertex loads."""
import hashlib
import struct

from .. import formats
from . import display_lists, display_meshes, mwo_graphics

LAYOUT = 'runtime-direct-model'
_MAX_SPAN = 1024 * 1024


def regions(image, snapshots, *, check=lambda: None):
    """Corroborate every loaded vertex against one unique mapping into the image."""
    found = {}
    for ram in snapshots:
        vertices, _ = display_lists._commands(ram, check)
        for number, (start, space, address, count) in enumerate(vertices):
            if not number % 32:
                check()
            if space != 128 or count < 4 or address+16*count > len(ram):
                continue
            first = bytes(ram[address:address+16*count])
            if len(set(first)) < 8:
                continue
            offset = image.find(first)
            if offset < 0 or image.find(first, offset+1) >= 0:
                continue
            delta = offset-address
            parsed = display_meshes.geometry(ram, start, min(len(ram), start+0x8000), {128: 0})
            if not parsed:
                continue
            end, points, faces = parsed
            # Flat rectangles are usually image sprites, not 3D geometry.
            if len(faces) < 3 or any(len({point[axis] for point in points}) < 2 for axis in range(3)):
                continue
            commands = bytes(ram[start:end])
            spans = []
            for word, pointer in struct.iter_unpack('>II', commands):
                n = display_lists._vertex_count(word)
                if not n:
                    continue
                if display_lists._space(pointer) != 128:
                    break
                physical = pointer & 0x1fffffff
                begin = physical+delta
                finish = begin+16*n
                if (physical+16*n > len(ram) or begin < 0 or finish > len(image)
                        or ram[physical:physical+16*n] != image[begin:finish]):
                    break
                spans.append((begin,finish))
            else:
                if not spans:
                    continue
                lo, hi = min(x for x,_ in spans), max(y for _,y in spans)
                if hi-lo > _MAX_SPAN:
                    continue
                base = lo-delta
                data = bytes(image[lo:hi])
                if not mwo_graphics._geometry(commands, data, base, 0, len(commands)):
                    continue
                digest = hashlib.sha256(data).hexdigest()
                key = (lo, hi, commands)
                found[key] = dict(offset=lo, size=hi-lo, kind='3d model', media='model', layout=LAYOUT,
                                  label='Runtime-backed local mesh', confidence='validated',
                                  vertices=len(points), triangles=len(faces), digest=digest,
                                  commands=commands.hex(), base=base,
                                  preview_settings=dict(source='rom', format='auto', offset=lo),
                                  reason='A unique captured vertex load maps this list to the analysis image; every other loaded vertex matches the same mapping.')
                if len(found) >= 128:
                    return list(found.values())
    return list(found.values())


def preview(image, asset, selection):
    lo, size = asset['offset'], asset['size']
    if not 0 <= lo <= len(image)-size or size > _MAX_SPAN:
        raise formats.AssetError('The captured model is outside the image. Scan ROM Explorer again.')
    data = bytes(image[lo:lo+size])
    if hashlib.sha256(data).hexdigest() != asset['digest']:
        raise formats.AssetError('The captured model changed. Scan ROM Explorer again.')
    try:
        commands = bytes.fromhex(asset['commands'])
    except (KeyError, ValueError, TypeError):
        raise formats.AssetError('The captured model commands are invalid. Scan ROM Explorer again.') from None
    parsed = mwo_graphics._geometry(commands, data, asset['base'], 0, len(commands))
    if not parsed:
        raise formats.AssetError('The captured geometry changed. Scan ROM Explorer again.')
    combined, offset, _ = parsed
    result = display_meshes.preview(combined, dict(offset=offset, size=len(commands),
        label=asset['label'], address_maps=[(128, -asset['base'])], preview_settings=asset['preview_settings']), {})
    result['note'] = 'Local captured geometry; scene placement, materials and animation are separate.'
    return result
