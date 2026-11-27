"""Bounded indexed polygon subsets in independently checked zlib containers."""
import struct

from .. import formats
from . import chunked_zlib

LAYOUT = 'chunked-indexed-polygon-mesh'
_SCAN_BUDGET = 128 * 1024 * 1024


def _nondegenerate(points,face):
    a,b,c = (points[i] for i in face)
    u = tuple(b[i]-a[i] for i in range(3))
    v = tuple(c[i]-a[i] for i in range(3))
    return any((u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]))


def _meshes(data, *, check=lambda: None):
    result = []
    for at in range(0,len(data)-31,4):
        if not at % 4096:
            check()
        vertices, count, polygons, faces, repeat, a, b, c = struct.unpack_from('>8I',data,at)
        if (not 3 <= count <= 4096 or not 2 <= faces <= 2048 or vertices % 2
                or vertices+count*6 > polygons or polygons+faces*32 != at
                or repeat != polygons or a or b or c):
            continue
        triangles = []
        for index in range(faces):
            pos = polygons+index*32
            kind, flags = struct.unpack_from('>II',data,pos)
            ids = struct.unpack_from('>4H',data,pos+8)
            if (kind != 0x21 or flags or any(x >= count for x in ids[:3]) or len(set(ids[:3])) != 3
                    or ids[3] != 0xffff and (ids[3] >= count or len(set(ids)) != 4)):
                break
            triangles.append(ids[:3])
            if ids[3] != 0xffff:
                triangles.append((ids[0],ids[2],ids[3]))
        else:
            points = [struct.unpack_from('>hhh',data,vertices+i*6) for i in range(count)]
            used = {i for face in triangles for i in face}
            if len(used) >= 4 and any(_nondegenerate(points,face) for face in triangles):
                result.append((at,points,triangles))
    return result


def regions(image, containers, *, check=lambda: None, **kwargs):
    result = []
    budget = _SCAN_BUDGET
    for item in containers:
        check()
        if item['expanded_size'] < 128:
            continue
        if item['expanded_size'] > budget:
            break
        budget -= item['expanded_size']
        record = chunked_zlib.unpack(image,item['offset'],check=check)
        if not record:
            continue
        meshes = _meshes(record[0],check=check)
        if not meshes:
            continue
        result.append(dict(offset=item['offset'],size=item['size'],kind='3d model',media='model',layout=LAYOUT,
                           label='Chunked local polygon subsets',confidence='validated',
                           vertices=sum(len(m[1]) for m in meshes),triangles=sum(len(m[2]) for m in meshes),
                           meshes=[dict(name=f'Subset {i+1}',vertices=len(m[1]),triangles=len(m[2]))
                                   for i,m in enumerate(meshes)],
                           reason='A checked zlib container bounds the vertex array and indexed polygon records; '
                                  'other geometry, placement, materials and animation are separate.',
                           preview_settings=dict(format='auto',source='rom',offset=item['offset'])))
    return result


def preview(image, asset, selection):
    record = chunked_zlib.unpack(image,asset['offset'])
    if record is None or record[1] != asset['size']:
        raise formats.AssetError('The compressed mesh changed. Rescan ROM Explorer.')
    meshes = _meshes(record[0])
    if not meshes:
        raise formats.AssetError('The polygon records changed. Rescan ROM Explorer.')
    chosen = formats.integer(selection.get('mesh',0),'Mesh',0,len(meshes)-1)
    _, vertices, faces = meshes[chosen]
    edges = {tuple(sorted((face[i],face[(i+1)%3]))) for face in faces for i in range(3)}
    return dict(media='model',vertices=vertices,triangles=len(faces),edges=sorted(edges),
                points=sorted({i for face in faces for i in face}),
                surfaces=[dict(indices=face,uv=[[0,0]]*3,colors=[[255,255,255,255]]*3,material=0)
                          for face in faces],materials=[],
                details=dict(format='Chunked local polygon subset',vertices=len(vertices),triangles=len(faces)),
                note='This is local geometry only; other polygons, scene placement, materials and animation are separate.',
                settings=dict(format='auto',source='rom',offset=asset['offset'],mesh=chosen))
