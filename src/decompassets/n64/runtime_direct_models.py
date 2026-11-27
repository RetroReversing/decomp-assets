"""Local non-planar meshes with cartridge-backed runtime vertex loads."""
import hashlib
import struct

from .. import formats
from . import display_lists, display_meshes, mwo_graphics

LAYOUT = 'runtime-direct-model'
_MAX_SPAN = 1024 * 1024


def regions(image, snapshots, *, check=lambda: None):
    """Corroborate every loaded vertex against one unique mapping into the image."""
    snapshots = list(snapshots)
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
    return list(found.values()) + _segmented(image, snapshots, check)


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


def _tasks(ram):
    """Find bounded graphics-task roots in captured big-endian RDRAM."""
    marker = b'\0\0\0\1'
    start = 0
    while (at := ram.find(marker, start)) >= 0:
        start = at + 4
        if at % 8 or at + 64 > len(ram):
            continue
        words = struct.unpack_from('>16I', ram, at)
        pointers = (words[2], words[4], words[6], words[12])
        if (all(0x80000000 <= p < 0x80000000 + len(ram) for p in pointers)
                and 0 < words[7] <= 0x800 and not words[12] % 8):
            yield words[12] & 0x1fffffff


def _segmented(image, snapshots, check):
    """Follow F3DEX2 task calls and segment updates before mapping local mesh loads."""
    found = {}
    for ram in snapshots:
        attempts = 0
        for task_number, root in enumerate(_tasks(ram)):
            if task_number >= 32:
                break
            segments, stack, pc = {}, [], root
            def resolve(pointer, segments=segments):
                space = pointer >> 24
                if space in (0x80, 0xa0):
                    return pointer & 0x1fffffff
                return segments[space] + (pointer & 0xffffff) if space in segments else None
            for step in range(65536):
                if not step % 1024:
                    check()
                if pc % 8 or not 0 <= pc <= len(ram)-8:
                    break
                word, pointer = struct.unpack_from('>II', ram, pc)
                op = word >> 24
                if word & 0xffff0000 == 0xdb060000 and (word & 0xffff) % 4 == 0:
                    slot = (word & 0xffff) // 4
                    if slot < 16 and pointer >> 24 in (0x80, 0xa0):
                        segments[slot] = pointer & 0x1fffffff
                elif op == 0xde:
                    target = resolve(pointer)
                    if target is None or target % 8 or not 0 <= target <= len(ram)-8:
                        break
                    if not (word >> 16) & 0xff:
                        stack.append(pc+8)
                    if len(stack) > 32:
                        break
                    pc = target
                    continue
                elif op == 0xdf:
                    if not stack:
                        break
                    pc = stack.pop()
                    continue
                elif op == 1 and (count := display_lists._vertex_count(word)) >= 4 and pointer >> 24 in segments:
                    attempts += 1
                    if attempts > 128:
                        break
                    address = resolve(pointer)
                    if address is not None and address+count*16 <= len(ram):
                        first = bytes(ram[address:address+count*16])
                        offset = image.find(first) if len(set(first)) >= 8 else -1
                        if offset >= 0 and image.find(first, offset+1) < 0:
                            maps = dict(segments)
                            maps[128] = 0
                            parsed = display_meshes.geometry(ram, pc, min(len(ram), pc+0x8000), maps)
                            if (parsed and len(parsed[2]) >= 3
                                    and all(len({point[axis] for point in parsed[1]}) >= 2 for axis in range(3))):
                                end, points, faces = parsed
                                delta = offset-address
                                commands = bytearray(ram[pc:end])
                                spans = []
                                for at in range(0, len(commands), 8):
                                    w, p = struct.unpack_from('>II', commands, at)
                                    n = display_lists._vertex_count(w)
                                    if not n:
                                        continue
                                    physical = resolve(p)
                                    begin = physical+delta if physical is not None else -1
                                    finish = begin+16*n
                                    if (physical is None or physical+16*n > len(ram) or begin < 0
                                            or finish > len(image) or ram[physical:physical+16*n] != image[begin:finish]):
                                        break
                                    struct.pack_into('>I', commands, at+4, 0x80000000 | physical)
                                    spans.append((begin, finish))
                                else:
                                    if spans:
                                        lo, hi = min(a for a,_ in spans), max(b for _,b in spans)
                                        base = lo-delta
                                        data = bytes(image[lo:hi])
                                        if (hi-lo <= _MAX_SPAN and mwo_graphics._geometry(bytes(commands), data, base, 0, len(commands))):
                                            key = (lo, hi, bytes(commands))
                                            found[key] = dict(offset=lo, size=hi-lo, kind='3d model', media='model', layout=LAYOUT,
                                                label='Runtime-backed local mesh', confidence='validated', vertices=len(points),
                                                triangles=len(faces), digest=hashlib.sha256(data).hexdigest(),
                                                commands=commands.hex(), base=base,
                                                preview_settings=dict(source='rom', format='auto', offset=lo),
                                                reason='A captured graphics task supplies segment mappings; every loaded vertex matches one unique image mapping.')
                                            if len(found) >= 128:
                                                return list(found.values())
                pc += 8
    return list(found.values())
