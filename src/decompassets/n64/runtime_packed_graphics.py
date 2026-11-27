"""Link runtime texture loads to indexed, compressed cartridge resources."""
import struct
from itertools import pairwise

from .. import formats
from . import display_lists, display_meshes, mwo_graphics
from .paired_resource_textures import _COMMAND, _LOAD

MODEL = "runtime-packed-model"
_MAX_EXPANDED = 128 * 1024 * 1024


def descriptors(image, check=lambda: None):
    """Bounded DMA descriptors with a size-prefixed LZSS resource."""
    seen = set()
    for at in range(0, len(image)-12, 4):
        if at % 0x40000 == 0:
            check()
        staging, start, end = struct.unpack_from('>3I', image, at)
        if not (0x80000000 <= staging < 0x80800000 and start % 16 == 0
                and 0 < start < end <= len(image) and 6 < end-start <= 4*1024*1024
                and image[start] == 1 and 0 < int.from_bytes(image[start+1:start+5], 'big') < end-start):
            continue
        if (start, end) not in seen:
            seen.add((start, end))
            yield start, end


def regions(image, snapshots, *, check=lambda: None, progress=lambda _: None):
    """Only assets whose decoded texels and palette are observed in runtime RAM."""
    snapshots = list(snapshots)
    candidates = list(descriptors(image, check))
    observations = []
    groups_by_snapshot = []
    for ram in snapshots:
        vertices, loads = display_lists._commands(ram, check)
        groups_by_snapshot.append((ram, display_lists._files(vertices, loads)))
        for match in _LOAD.finditer(ram):
            if match.start() % 8:
                continue
            source, *_ = _COMMAND.iter_unpack(match[0])
            pointer = source[1] & 0x1fffffff
            prefix = ram[pointer:pointer+64]
            if len(prefix) == 64 and len(set(prefix)) >= 8:
                observations.append((ram, match.start(), match.end(), pointer, prefix))
    found = []
    expanded = 0
    for number, (start, end) in enumerate(candidates):
        if number % 16 == 0:
            check(); progress(dict(phase='Checking runtime packed textures', done=number, total=len(candidates)))
        parsed = mwo_graphics.inflate(image[start:end])
        if not parsed:
            continue
        data, used = parsed
        expanded += len(data)
        if expanded > _MAX_EXPANDED:
            break
        if any(image[start+used:end]) or len(data) < 64:
            continue
        items = {}
        bases = {}
        for ram, command_start, command_end, pointer, prefix in observations:
            # A later resource can have replaced the block header. A unique
            # observed texel prefix identifies its original address instead.
            offset = data.find(prefix)
            if offset < 0 or data.find(prefix, offset+1) >= 0:
                continue
            base = pointer-offset
            if base < 0 or base+len(data) > len(ram):
                continue
            bases[(id(ram), base)] = ram
            group = dict(start=max(0, command_start-64) & ~7,
                         end=min(len(ram)-8, command_end+128) & ~7)
            for item in mwo_graphics.texture_items(ram, group, data, base):
                options = item['preview_settings']
                pixel = options['offset']
                count = item['texel_bytes']
                if ram[base+pixel:base+pixel+count] != data[pixel:pixel+count]:
                    continue
                if item['palettes']:
                    palette = options['palette_offset']
                    size = 2*item['palette_entries'][0]
                    if ram[base+palette:base+palette+size] != data[palette:palette+size]:
                        continue
                key = tuple(options.values())
                items.setdefault(key, item)
        if items:
            textures = list(items.values())
            first = textures[0]
            found.append(dict(offset=start, size=used, expanded_size=len(data), kind='image',
                              layout=mwo_graphics.TEXTURES, label='Runtime-backed packed textures',
                              confidence='validated', textures=textures, frames=1, palettes=first['palettes'],
                              levels=first['levels'], preview_settings=dict(first['preview_settings'] | {
                                  'source':'rom', 'offset':start}),
                              reason='The bounded DMA descriptor and LZSS resource match captured RAM; '
                                     'runtime display commands identify the texture and palette.'))
        meshes = []
        seen_commands = set()
        for (ram_id, base), ram in bases.items():
            groups = next(groups for snapshot, groups in groups_by_snapshot if id(snapshot) == ram_id)
            for group in groups:
                refs = [(address, count) for _, space, address, count in group['vertices']
                        if space == 128 and base <= address and address+16*count <= base+len(data)]
                if not refs:
                    continue
                end_at = min(group['end']+96, len(ram)) & ~7
                for first, last in pairwise([*display_lists._starts(ram, group), end_at]):
                    if len(meshes) >= 256:
                        break
                    parsed = mwo_graphics._geometry(ram, data, base, first, last)
                    if not parsed:
                        continue
                    commands = bytes(ram[first:last])
                    if commands in seen_commands:
                        continue
                    valid = True
                    for word, address in struct.iter_unpack('>II', commands):
                        count = display_lists._vertex_count(word)
                        if count:
                            pointer = address & 0x1fffffff
                            offset = pointer-base
                            if offset < 0 or ram[pointer:pointer+16*count] != data[offset:offset+16*count]:
                                valid = False
                                break
                    if not valid:
                        continue
                    _, _, (_, vertices, faces) = parsed
                    seen_commands.add(commands)
                    meshes.append(dict(name=f'Mesh {len(meshes)+1}', commands=commands.hex(), base=base,
                                       vertices=len(vertices), triangles=len(faces)))
        if meshes:
            found.append(dict(offset=start, size=used, kind='3d model', media='model', layout=MODEL,
                              label='Runtime-backed packed models', confidence='validated', meshes=meshes,
                              vertices=sum(m['vertices'] for m in meshes), triangles=sum(m['triangles'] for m in meshes),
                              preview_settings=dict(source='rom', format='auto', offset=start),
                              reason='Captured display lists and their vertex loads match this decoded resource.'))
    return found


def preview_model(image, asset, selection):
    start = asset['offset']
    packed = mwo_graphics.inflate(image[start:start+asset['size']])
    index = formats.integer(selection.get('mesh', 0), 'Mesh', 0, len(asset['meshes'])-1)
    item = asset['meshes'][index]
    commands = bytes.fromhex(item['commands'])
    parsed = mwo_graphics._geometry(commands, packed[0], item['base'], 0, len(commands)) if packed else None
    if not parsed:
        raise formats.AssetError('The packed model changed. Scan ROM Explorer again.')
    combined, offset, _ = parsed
    settings = dict(source='rom', format='auto', offset=start, mesh=index)
    result = display_meshes.preview(combined, dict(offset=offset, size=len(combined)-offset,
        label=asset['label'], address_maps=[(128, -item['base'])], preview_settings=settings), {})
    result['note'] = 'Local runtime mesh; scene placement, materials and animation are separate.'
    return result
