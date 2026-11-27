"""Local meshes in paired vertex and triangle resources in paged archives."""
import re
import struct

from .. import formats
from . import big_pages

LAYOUT = 'big-tagged-meshes'


def _mesh(data, at):
    if at+8 > len(data) or data[at:at+4] != b'VER\0':
        return None
    size, = struct.unpack_from('<I', data, at+4)
    shape = at+8+size+4
    if (not 48 <= size <= 8192*16 or size % 16 or shape+16 > len(data)
            or any(data[at+8+size:shape]) or data[shape:shape+4] != b'SHP\0'):
        return None
    count = size//16
    if any(struct.unpack_from('>H', data, at+8+i*16+6)[0] for i in range(count)):
        return None
    length, = struct.unpack_from('<I', data, shape+4)
    end = shape+8+length
    if not 9 <= length <= 0x100000 or end+7 > len(data):
        return None
    cursor, first, active, faces = shape+16, 0, 0, []
    while cursor < end:
        op = data[cursor]
        if op == 0x64 and cursor+4 <= end:
            active, first = data[cursor+1], int.from_bytes(data[cursor+2:cursor+4], 'big')
            cursor += 4
            if not active or first+active > count:
                return None
        elif op == 0x67 and cursor+4 <= end:
            triangle = data[cursor+1:cursor+4]
            cursor += 4
            if not active or max(triangle) >= active:
                return None
            faces.append(tuple(first+i for i in triangle))
        elif op == 0x6a and cursor+8 <= end:
            cursor += 8
        elif op == 0x69 and cursor == end-1 and data[cursor+1:cursor+4] == b'\x01\0\0' and faces:
            points = [struct.unpack_from('>3h', data, at+8+i*16) for i in range(count)]
            return points, faces, end+7
        else:
            return None
    return None


def from_archive(archive, data, check=lambda: None):
    groups = {}
    for match in re.finditer(b'VER\0', data):
        at = match.start()
        check()
        parsed = _mesh(data, at)
        if not parsed:
            continue
        points, faces, end = parsed
        lo, hi = big_pages.physical(archive, at, end-at)
        member = dict(resource=at, resource_size=end-at)
        mesh = dict(name=f'Mesh {len(groups)+1}', vertices=len(points), triangles=len(faces))
        if lo not in groups:
            groups[lo] = dict(offset=lo, size=hi-lo, kind='3d model', media='model', layout=LAYOUT,
                              label='Paged tagged model', confidence='validated', archive=archive[0],
                              members=[member], meshes=[mesh], nodes=1, triangles=len(faces),
                              reason='Bounded tagged vertex and triangle records resolve every index.',
                              preview_settings=dict(source='rom', format='auto', offset=lo, mesh=0))
        else:
            group = groups[lo]
            group['members'].append(member)
            group['meshes'].append(mesh)
            group['nodes'] += 1
            group['triangles'] += len(faces)
            group['size'] = max(group['size'], hi-lo)
    return list(groups.values())


def preview(image, asset, selection):
    archive = next((a for a in big_pages.archives(image) if a[0] == asset['archive']), None)
    index = formats.integer(selection.get('mesh', 0), 'Mesh', 0, len(asset['members'])-1)
    member = asset['members'][index]
    data = big_pages.extract(image, archive, member['resource'], member['resource_size']) if archive else None
    decoded = _mesh(data, 0) if data else None
    if not decoded:
        raise formats.AssetError('The model archive changed. Scan ROM Explorer again.')
    points, faces, _ = decoded
    edges = {tuple(sorted((face[i-1], face[i]))) for face in faces for i in range(3)}
    return dict(media='model', vertices=points, triangles=len(faces), edges=sorted(edges),
                points=sorted({i for face in faces for i in face}),
                surfaces=[dict(indices=face, uv=[[0,0]]*3, colors=[[255]*4]*3, material=0) for face in faces],
                materials=[], details=dict(format='Paged tagged model', vertices=len(points), triangles=len(faces)),
                note='Local geometry; scene placement, materials and animation are separate.',
                settings=dict(asset['preview_settings'], mesh=index))
