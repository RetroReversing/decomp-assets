"""Link runtime texture loads to indexed, compressed cartridge resources."""
import re
import struct
import zlib
from itertools import islice, pairwise

from .. import formats, rnc
from . import block16_graphics, display_lists, display_meshes, mwo_graphics, ring12_graphics, table_lz_graphics
from .paired_resource_textures import _COMMAND, _LOAD

MODEL = "runtime-packed-model"
MIO_TEXTURES = "runtime-mio0-textures"
ERZ_TEXTURES = "runtime-erz-textures"
RNC_TEXTURES = "runtime-rnc-textures"
DEFLATE_TEXTURES = "runtime-deflate-textures"
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


def unpack_mio(image):
    """Decode one bounded MIO0 stream and retain its exact stored extent."""
    try:
        data, codec, used = formats.unpack_extent(image)
    except formats.AssetError:
        return None
    return (data, used) if codec == 'MIO0' else None


def unpack_erz(image):
    """Decode one bounded ERZ block only after both checksums pass."""
    if image[:4] not in (b'ERZ\x01', b'ERZ\x02'):
        return None
    try:
        return rnc.unpack_at(image, 0, max_output=formats.MAX_BYTES, max_packed=formats.MAX_BYTES)
    except rnc.RncError:
        return None


def unpack_rnc(image):
    """Decode a bounded RNC block only after both checksums pass."""
    if image[:4] not in (b'RNC\x01', b'RNC\x02'):
        return None
    try:
        return rnc.unpack_at(image, 0, max_output=formats.MAX_BYTES, max_packed=formats.MAX_BYTES)
    except rnc.RncError:
        return None


def unpack_deflate(image):
    """Decode a bounded raw DEFLATE stream and require its end marker."""
    try:
        decoder = zlib.decompressobj(-15)
        data = decoder.decompress(image, formats.MAX_BYTES + 1)
        if not decoder.eof or len(data) > formats.MAX_BYTES:
            return None
        return data, len(image)-len(decoder.unused_data)
    except zlib.error:
        return None


def _deflate_candidates(image, check):
    for at in range(16, len(image), 16):
        if at % 0x40000 == 0:
            check()
        if image[at-4:at] == b'\0'*4 and image[at]:
            yield at, min(len(image),at+formats.MAX_BYTES), 'deflate'


def regions(image, snapshots, *, check=lambda: None, progress=lambda _: None):
    """Only assets whose decoded texels and palette are observed in runtime RAM."""
    snapshots = list(snapshots)
    if not snapshots:
        return []
    candidates = [(start,end,'mwo') for start,end in descriptors(image, check)]
    candidates += [(start,end,'table-lz') for start,end in table_lz_graphics.descriptors(image, check)]
    candidates += [(start,end,'ring12') for start,end in ring12_graphics.descriptors(image, check)]
    candidates += [(start,end,'block16') for start,end in block16_graphics.descriptors(image, check)]
    candidates += [(m.start(), min(len(image), m.start()+formats.MAX_BYTES), 'mio0')
                   for m in re.finditer(b'MIO0', image) if m.start() % 4 == 0]
    candidates += [(m.start(), min(len(image), m.start()+formats.MAX_BYTES), 'erz')
                   for m in re.finditer(b'ERZ[\x01\x02]', image) if m.start() % 2 == 0]
    candidates += [(m.start(), min(len(image), m.start()+formats.MAX_BYTES), 'rnc')
                   for m in re.finditer(b'RNC[\x01\x02]', image) if m.start() % 2 == 0]
    # Raw streams have no signature. Only probe aligned boundaries after zero
    # padding; complete runtime pixel or vertex matches are required below.
    candidates += list(islice(_deflate_candidates(image,check),4096))
    from . import runtime_deflate_models
    model_observations = runtime_deflate_models.observations(snapshots, check)
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
            for shift in (0, 64, 128, 256, 512, 1024, 1536, 1792):
                prefix = ram[pointer+shift:pointer+shift+64]
                if len(prefix) == 64 and len(set(prefix)) >= 8:
                    observations.append((ram, match.start(), match.end(), pointer, shift, prefix))
                    break
    found = []
    expanded = 0
    for number, (start, end, codec) in enumerate(candidates):
        if number % 16 == 0:
            check(); progress(dict(phase='Checking runtime packed textures', done=number, total=len(candidates)))
        parsed = (mwo_graphics.inflate(image[start:end]) if codec == 'mwo'
                  else table_lz_graphics.inflate(memoryview(image)[start:end], check) if codec == 'table-lz'
                  else ring12_graphics.inflate(memoryview(image)[start:end], check) if codec == 'ring12'
                  else block16_graphics.inflate(memoryview(image)[start:end], check) if codec == 'block16'
                  else unpack_erz(image[start:end]) if codec == 'erz'
                  else unpack_rnc(image[start:end]) if codec == 'rnc'
                  else unpack_deflate(image[start:end]) if codec == 'deflate' else unpack_mio(image[start:end]))
        if not parsed:
            continue
        data, used = parsed
        expanded += len(data)
        if expanded > _MAX_EXPANDED:
            break
        if (len(data) < 64 or codec == 'mwo' and any(image[start+used:end])
                or codec in ('table-lz', 'ring12') and end-start-used > 15):
            continue
        if codec == 'deflate' and model_observations:
            local_meshes = runtime_deflate_models.meshes(data, model_observations, check)
            if local_meshes:
                found.append(dict(offset=start, size=used, kind='3d model', media='model',
                                  layout=runtime_deflate_models.LAYOUT, codec=codec,
                                  label='Runtime-backed compressed models', confidence='validated',
                                  meshes=local_meshes, vertices=sum(m['vertices'] for m in local_meshes),
                                  triangles=sum(m['triangles'] for m in local_meshes),
                                  preview_settings=dict(source='rom', format='auto', offset=start),
                                  reason='A captured graphics task calls these lists; their relocated vertex loads match the decoded resource.'))
        items = {}
        bases = {}
        for ram, command_start, command_end, pointer, shift, prefix in observations:
            # Sparse/repeated graphics can share a prefix. Try only a small
            # bounded set; the complete texels and palette must still match.
            offsets = []
            at = data.find(prefix)
            while at >= 0 and len(offsets) < 5:
                offsets.append(at)
                at = data.find(prefix, at+1)
            if not offsets or len(offsets) > 4 or codec != 'ring12' and len(offsets) != 1:
                continue
            for offset in offsets:
                base = pointer+shift-offset
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
                              layout=(mwo_graphics.TEXTURES if codec == 'mwo' else table_lz_graphics.TEXTURES
                                      if codec == 'table-lz' else ring12_graphics.TEXTURES if codec == 'ring12'
                                      else block16_graphics.TEXTURES if codec == 'block16'
                                      else ERZ_TEXTURES if codec == 'erz' else RNC_TEXTURES if codec == 'rnc'
                                      else DEFLATE_TEXTURES if codec == 'deflate'
                                      else MIO_TEXTURES), codec=codec,
                              label='Runtime-backed packed textures',
                              confidence='validated', textures=textures, frames=1, palettes=first['palettes'],
                              levels=first['levels'], preview_settings=dict(first['preview_settings'] | {
                                  'source':'rom', 'offset':start}),
                              reason='The bounded resource and decoded pixels match captured RAM; '
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
                              label='Runtime-backed packed models', confidence='validated', meshes=meshes, codec=codec,
                              vertices=sum(m['vertices'] for m in meshes), triangles=sum(m['triangles'] for m in meshes),
                              preview_settings=dict(source='rom', format='auto', offset=start),
                              reason='Captured display lists and their vertex loads match this decoded resource.'))
    from . import runtime_direct_models, runtime_zip_models
    return (found + runtime_direct_models.regions(image, snapshots, check=check)
            + runtime_zip_models.regions(image, snapshots, check=check, progress=progress))


def preview_model(image, asset, selection):
    start = asset['offset']
    codec = asset.get('codec')
    packed = (table_lz_graphics.inflate(image[start:start+asset['size']]) if codec == 'table-lz'
              else ring12_graphics.inflate(image[start:start+asset['size']]) if codec == 'ring12'
              else block16_graphics.inflate(image[start:start+asset['size']]) if codec == 'block16'
              else unpack_mio(image[start:start+asset['size']]) if codec == 'mio0'
              else unpack_erz(image[start:start+asset['size']]) if codec == 'erz'
              else unpack_rnc(image[start:start+asset['size']]) if codec == 'rnc'
              else unpack_deflate(image[start:start+asset['size']]) if codec == 'deflate'
              else mwo_graphics.inflate(image[start:start+asset['size']]))
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
