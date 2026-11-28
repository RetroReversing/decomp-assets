"""Runtime-called meshes with relocated segment-zero pointers in DEFLATE data."""

import struct

from .. import formats
from . import display_lists, display_meshes, runtime_direct_models, runtime_zip_models

LAYOUT = 'runtime-deflate-model'
_MAX_CALLS = 4096
_MAX_MESHES = 256


def _cull(word, argument):
    # F3DEX G_CULLDL changes visibility, not local geometry.
    return word == 0xbe000000 and argument <= 0xffff


def _calls(ram, check):
    """Follow bounded F3DEX task calls; segment zero is physical RDRAM."""
    roots = list(runtime_direct_models._tasks(ram))[:32]
    stack, visited, targets = roots, set(), set()
    while stack and len(visited) < 65536 and len(targets) < _MAX_CALLS:
        pc = stack.pop()
        while 0 <= pc <= len(ram)-8 and not pc % 8 and pc not in visited and len(visited) < 65536:
            if not len(visited) % 1024:
                check()
            visited.add(pc)
            word, pointer = struct.unpack_from('>II', ram, pc)
            opcode = word >> 24
            if opcode == 6 and not word & 0xfeffff:
                if pointer >> 24 in (0, 0x80, 0xa0):
                    target = pointer & 0x1fffffff
                    if target % 8 == 0 and target+8 <= len(ram):
                        targets.add(target)
                        stack.append(target)
                if word & 0x10000:
                    break
            if opcode == 0xb8:
                break
            pc += 8
    return targets


def observations(snapshots, check):
    result = []
    for ram in snapshots:
        for at in sorted(_calls(ram, check)):
            word, pointer = struct.unpack_from('>II', ram, at)
            count = display_lists._vertex_count(word)
            if word >> 24 != 4 or pointer >> 24 or count < 4 or pointer+count*16 > len(ram):
                continue
            vertices = bytes(ram[pointer:pointer+count*16])
            if len(set(vertices)) >= 8:
                result.append((ram, at, pointer, vertices))
    return result


def _matches(ram, data, base, start, end):
    if base < 0 or base+end > len(ram):
        return False
    for at in range(start, end, 8):
        word, pointer = struct.unpack_from('>II', data, at)
        live_word, live_pointer = struct.unpack_from('>II', ram, base+at)
        if word != live_word:
            return False
        count = display_lists._vertex_count(word)
        if count:
            if pointer >> 24 or live_pointer != base+pointer or pointer+count*16 > len(data):
                return False
            if data[pointer:pointer+count*16] != ram[live_pointer:live_pointer+count*16]:
                return False
        elif word >> 24 in (0xfd, 0x03):
            # These state commands may relocate textures or lights; neither
            # changes the local triangles being previewed.
            continue
        elif pointer != live_pointer:
            return False
    return True


def meshes(data, observed, check):
    found = {}
    for number, (ram, at, pointer, vertices) in enumerate(observed):
        if not number % 128:
            check()
        offset = data.find(vertices)
        if offset < 0 or data.find(vertices, offset+1) >= 0:
            continue
        base = pointer-offset
        start = at-base
        if start < 0 or start % 8 or start >= len(data):
            continue
        parsed = display_meshes.geometry(data, start, len(data), {0: 0}, extra_state=_cull)
        if not parsed:
            continue
        end, points, faces = parsed
        used = sorted({i for face in faces for i in face})
        if (len(faces) < 3 or not runtime_zip_models._nonplanar([points[i] for i in used])
                or not _matches(ram, data, base, start, end)):
            continue
        found.setdefault((start, end), dict(name=f'Mesh {len(found)+1}', offset=start, size=end-start,
                                            vertices=len(points), triangles=len(faces)))
        if len(found) >= _MAX_MESHES:
            break
    return list(found.values())


def preview(image, asset, selection):
    from . import runtime_packed_graphics
    start, size = asset['offset'], asset['size']
    if start < 0 or size <= 0 or start+size > len(image):
        raise formats.AssetError('The compressed model resource changed. Scan ROM Explorer again.')
    packed = runtime_packed_graphics.unpack_deflate(image[start:start+size])
    if not packed or packed[1] != size:
        raise formats.AssetError('The compressed model resource changed. Scan ROM Explorer again.')
    index = formats.integer(selection.get('mesh', 0), 'Mesh', 0, len(asset['meshes'])-1)
    item = asset['meshes'][index]
    settings = dict(source='rom', format='auto', offset=start, mesh=index)
    result = display_meshes.preview(packed[0], dict(offset=item['offset'], size=item['size'],
        label=asset['label'], address_maps=[(0, 0)], preview_settings=settings), {}, extra_state=_cull)
    result['note'] = 'Local geometry from a runtime-called list; scene placement, materials and animation are separate.'
    return result
