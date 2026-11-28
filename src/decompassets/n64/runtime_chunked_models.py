"""Local F3DEX mesh batches proven by runtime and compressed resources."""

import struct

from .. import formats
from . import chunked_lz_images, display_lists, display_meshes, runtime_direct_models, runtime_zip_models

LAYOUT = 'runtime-chunked-model'
_END = bytes.fromhex('b800000000000000')


def observations(snapshots, check=lambda: None):
    found = {}
    for ram in snapshots:
        for root in list(runtime_direct_models._tasks(ram))[:32]:
            segments, stack, pc = {}, [], root

            def resolve(pointer, segments=segments):
                slot = pointer >> 24
                if slot in (0x80, 0xa0):
                    return pointer & 0x1fffffff
                return segments.get(slot, -0x1000000) + (pointer & 0xffffff)

            for step in range(65536):
                if not step % 1024:
                    check()
                if pc % 8 or not 0 <= pc <= len(ram) - 8:
                    break
                word, pointer = struct.unpack_from('>II', ram, pc)
                opcode = word >> 24
                if word >> 24 == 0xbc and word & 255 == 6 and (word >> 8 & 0xffff) % 4 == 0:
                    slot = (word >> 8 & 0xffff) // 4
                    if slot < 16 and pointer >> 24 in (0x80, 0xa0):
                        segments[slot] = pointer & 0x1fffffff
                elif opcode == 6:
                    target = resolve(pointer)
                    if not 0 <= target <= len(ram) - 8 or target % 8 or len(stack) >= 32:
                        break
                    if not word & 0x10000:
                        stack.append(pc + 8)
                    pc = target
                    continue
                elif opcode == 0xb8:
                    if not stack:
                        break
                    pc = stack.pop()
                    continue
                elif opcode == 4:
                    count = display_lists._vertex_count(word)
                    address = resolve(pointer)
                    end = pc + 8
                    while end + 8 <= len(ram) and end - pc <= 1024 and ram[end] in (0xbf, 0xb1):
                        end += 8
                    if count >= 4 and end > pc + 8 and 0 <= address <= len(ram) - count * 16:
                        commands = bytes(ram[pc:end])
                        vertices = bytes(ram[address:address + count * 16])
                        if len(set(vertices)) >= 8:
                            found.setdefault((commands, vertices), None)
                            if len(found) >= 4096:
                                return list(found)
                pc += 8
    return list(found)


def _combined(data, commands, vertex):
    if not 0 <= vertex < min(len(data), 0x1000000) or len(commands) < 16 or len(commands) % 8:
        raise formats.AssetError('The captured mesh changed. Scan ROM Explorer again.')
    commands = bytearray(commands)
    struct.pack_into('>I', commands, 4, 0x80000000 | vertex)
    start = (len(data) + 7) & ~7
    return data + bytes(start - len(data)) + bytes(commands) + _END, start


def regions(image, snapshots, *, check=lambda: None, progress=lambda _: None):
    candidates = observations(snapshots, check)
    if not candidates:
        return []
    found, visited, total = [], set(), 0
    for directory, entries in chunked_lz_images.directories(image, check):
        for offset, size, expanded in entries:
            check()
            if offset in visited:
                continue
            visited.add(offset)
            data = chunked_lz_images.decode(image[offset:offset + size], expanded)
            if not data:
                continue
            meshes, seen = [], set()
            for commands, vertices in candidates:
                vertex = data.find(vertices)
                if vertex < 0 or data.find(vertices, vertex + 1) >= 0:
                    continue
                command = data.find(commands)
                if command < 0 or data.find(commands, command + 1) >= 0:
                    continue
                combined, start = _combined(data, commands, vertex)
                parsed = display_meshes.geometry(combined, start, len(combined), {128: 0})
                if (not parsed or len(parsed[2]) < 3
                        or not runtime_zip_models._nonplanar([parsed[1][i] for i in sorted({i for face in parsed[2] for i in face})])):
                    continue
                key = command, vertex
                if key in seen:
                    continue
                seen.add(key)
                meshes.append(dict(name=f'Mesh {len(meshes) + 1}', command=command, command_size=len(commands),
                                   vertex=vertex, vertices=len(parsed[1]), triangles=len(parsed[2])))
                total += 1
                if total >= 512:
                    break
            if meshes:
                found.append(dict(offset=offset, size=size, expanded=expanded, directory=directory, kind='3d model',
                                  media='model', layout=LAYOUT, label=f'Runtime-backed resource · {len(meshes)} meshes',
                                  confidence='validated', meshes=meshes, vertices=sum(m['vertices'] for m in meshes),
                                  triangles=sum(m['triangles'] for m in meshes),
                                  preview_settings=dict(source='rom', format='auto', offset=offset),
                                  reason='The task calls this batch and its commands and all loaded vertices match one decoded resource.'))
            if total >= 512:
                return found
    return found


def preview(image, asset, selection):
    offset, size = asset['offset'], asset['size']
    data = chunked_lz_images.decode(image[offset:offset + size], asset['expanded'])
    index = formats.integer(selection.get('mesh', 0), 'Mesh', 0, len(asset['meshes']) - 1)
    item = asset['meshes'][index]
    if not data or item['command'] + item['command_size'] > len(data):
        raise formats.AssetError('The compressed mesh changed. Scan ROM Explorer again.')
    commands = data[item['command']:item['command'] + item['command_size']]
    combined, start = _combined(data, commands, item['vertex'])
    settings = dict(source='rom', format='auto', offset=offset, mesh=index)
    result = display_meshes.preview(combined, dict(offset=start, size=len(combined) - start,
        label=asset['label'], address_maps=[(128, 0)], preview_settings=settings), {})
    result['note'] = 'One runtime-captured local mesh batch; scene placement, materials and animation are separate.'
    return result
