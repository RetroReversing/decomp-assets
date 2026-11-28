"""Local meshes whose runtime vertex loads match validated ZIP members."""

import struct

from .. import archives, formats
from . import display_lists, display_meshes

LAYOUT = 'runtime-zip-model'
_END = bytes.fromhex('df00000000000000')
_MAX_CANDIDATES = 4096
_MAX_MESHES = 512
_MAX_EXPANDED = 128 * 1024 * 1024


def _nonplanar(points):
    if len(points) < 4:
        return False
    origin = points[0]
    vectors = [(x-origin[0], y-origin[1], z-origin[2]) for x,y,z in points[1:]]
    first = next((v for v in vectors if any(v)), None)
    if first is None:
        return False
    for second in vectors:
        normal = (first[1]*second[2]-first[2]*second[1], first[2]*second[0]-first[0]*second[2],
                  first[0]*second[1]-first[1]*second[0])
        if any(normal):
            return any(sum(a*b for a,b in zip(normal, third)) for third in vectors)
    return False


def _batches(snapshots, check):
    """A single vertex load and its immediately following triangle commands."""
    result = {}
    for ram in snapshots:
        vertices, _ = display_lists._commands(ram, check)
        for index, (at, space, address, count) in enumerate(vertices):
            if not index % 128:
                check()
            if (space != 128 or count < 4 or address+count*16 > len(ram)
                    or ram[at] != 1):
                continue
            vertex = bytes(ram[address:address+count*16])
            if len(set(vertex[:32])) < 8:
                continue
            end = at+8
            while end+8 <= len(ram) and end-at <= 1024 and ram[end] in (5, 6):
                end += 8
            if end == at+8:
                continue
            commands = bytes(ram[at:end])
            # The runtime pointer is replaced by the member-relative offset
            # after all vertices are verified against the decoded member.
            key = vertex, commands[:4]+bytes(4)+commands[8:]
            result.setdefault(key, (vertex, commands))
            if len(result) >= _MAX_CANDIDATES:
                return list(result.values())
    return list(result.values())


def _combined(data, commands, vertex_offset):
    if not 0 <= vertex_offset < min(len(data), 0x1000000):
        raise formats.AssetError('The captured mesh offset is outside its archive member.')
    commands = bytearray(commands)
    if len(commands) < 16 or len(commands) % 8 or commands[0] != 1:
        raise formats.AssetError('The captured mesh commands changed. Scan ROM Explorer again.')
    struct.pack_into('>I', commands, 4, 0x80000000 | vertex_offset)
    offset = (len(data)+7) & ~7
    return data+bytes(offset-len(data))+bytes(commands)+_END, offset


def regions(image, snapshots, *, check=lambda: None, progress=lambda _: None):
    """Only expose complete vertex batches and triangles seen in runtime RAM."""
    candidates = _batches(snapshots, check)
    if not candidates:
        return []
    found = []
    expanded = total = 0
    members = archives.zip_members(image, check=check)
    for number, member in enumerate(members):
        check()
        if not number % 16:
            progress(dict(phase='Checking archive-backed runtime meshes', done=number, total=len(members)))
        if not 0 < member['expanded'] <= formats.MAX_BYTES:
            continue
        try:
            data = archives.member_bytes(image, member)
        except formats.AssetError:
            continue
        expanded += len(data)
        if expanded > _MAX_EXPANDED:
            break
        meshes = []
        seen = set()
        for vertex, commands in candidates:
            at = data.find(vertex)
            if at < 0 or data.find(vertex, at+1) >= 0:
                continue
            combined, start = _combined(data, commands, at)
            parsed = display_meshes.geometry(combined, start, len(combined), {128: 0}, vertex_flag_mask=0xffff)
            if (not parsed or len(parsed[2]) < 3
                    or not _nonplanar([parsed[1][i] for i in sorted({i for face in parsed[2] for i in face})])):
                continue
            key = at, commands[:4]+commands[8:]
            if key in seen:
                continue
            seen.add(key)
            normalized = bytearray(commands)
            struct.pack_into('>I', normalized, 4, 0x80000000 | at)
            meshes.append(dict(name=f'Mesh {len(meshes)+1}', vertex_offset=at, commands=normalized.hex(),
                               vertices=len(parsed[1]), triangles=len(parsed[2])))
            total += 1
            if total >= _MAX_MESHES:
                break
        if meshes:
            found.append(dict(offset=member['offset'], size=member['size'], kind='3d model', media='model',
                              layout=LAYOUT, label=f'Runtime-backed archive meshes · {member["name"]}', confidence='validated',
                              member=member, meshes=meshes, vertices=sum(m['vertices'] for m in meshes),
                              triangles=sum(m['triangles'] for m in meshes),
                              preview_settings=dict(source='rom', format='auto', offset=member['offset']),
                              reason='Captured vertex loads match a CRC-checked archive member; adjacent triangle commands resolve against those vertices.'))
        if total >= _MAX_MESHES:
            break
    return found


def preview(image, asset, selection):
    member = asset['member']
    if member['offset'] != asset['offset'] or member['size'] != asset['size']:
        raise formats.AssetError('The archive member changed. Scan ROM Explorer again.')
    data = archives.member_bytes(image, member)
    index = formats.integer(selection.get('mesh', 0), 'Mesh', 0, len(asset['meshes'])-1)
    item = asset['meshes'][index]
    try:
        commands = bytes.fromhex(item['commands'])
    except ValueError:
        raise formats.AssetError('The captured mesh commands changed. Scan ROM Explorer again.') from None
    combined, start = _combined(data, commands, item['vertex_offset'])
    settings = dict(source='rom', format='auto', offset=asset['offset'], mesh=index)
    result = display_meshes.preview(combined, dict(offset=start, size=len(combined)-start,
        label=asset['label'], address_maps=[(128, 0)], preview_settings=settings), {}, vertex_flag_mask=0xffff)
    result['note'] = 'One runtime-captured local mesh batch; scene placement, materials and animation are separate.'
    return result
