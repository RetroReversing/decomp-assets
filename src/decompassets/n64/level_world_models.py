"""Local level meshes from bounded spatial-tree display-list fragments."""
import struct

from .. import formats
from . import display_meshes, level_logos, level_world

LAYOUT = 'level-world-meshes'
_BASE = 0x8024b000
_MAX_LEAVES = 4096
_SECTIONS_PER_MESH = 64


def meshes(data, check=lambda: None):
    image = bytearray(data)
    def word(at):
        return struct.unpack_from('>I', image, at)[0]
    if len(image) < 0x90:
        return []
    scene = word(0)-_BASE
    if not 0 <= scene <= len(image)-0x60:
        return []
    vertex = word(scene+0x30)-_BASE
    root = word(scene)-_BASE
    count = word(scene+0x18)
    if not 1 <= count <= 100000 or not 0 <= vertex <= len(image)-count*16 or not 0 <= root <= len(image)-24:
        return []
    pending, visited, rows = [root], set(), []
    while pending and len(visited) < 2*_MAX_LEAVES and len(rows) < _MAX_LEAVES:
        check()
        at = pending.pop()
        if at in visited or not 0 <= at <= len(image)-24 or at % 4:
            continue
        visited.add(at)
        kind = image[at+12]
        if kind == 1:
            pending.extend((word(at+16)-_BASE, word(at+20)-_BASE))
            continue
        if kind != 2:
            continue
        cursor, parts, closed = at+24, [], False
        for _ in range(512):
            if cursor+8 > len(image):
                break
            flags, size = struct.unpack_from('>HH', image, cursor)
            if not flags and not size:
                closed = word(cursor+4) == 0xcdcdcdcd
                break
            if flags & 1:
                if size < 8 or size % 8 or cursor+size > len(image):
                    break
                cursor += size
                continue
            start, end = cursor+16, cursor+16+size
            if not size or size % 8 or end+8 > len(image) or size > 0x4000:
                break
            saved = image[end:end+8]
            image[end:end+8] = b'\xdf\0\0\0\0\0\0\0'
            parsed = display_meshes.geometry(image, start, end+8, {1: vertex}, vertex_end=vertex+count*16)
            image[end:end+8] = saved
            if parsed:
                _, vertices, faces = parsed
                parts.append((vertices,faces))
            cursor = end
        if parts and closed:
            rows.append(dict(offset=at, vertices=sum(len(v) for v,_ in parts),
                             triangles=sum(len(f) for _,f in parts), parts=parts))
    return rows


def regions(image, *, check=lambda: None, **kwargs):
    result = []
    for row in level_logos.records(image):
        check()
        try:
            data = level_world.unpack(image, row)
        except formats.AssetError:
            continue
        found = meshes(data, check)
        if not found:
            continue
        listed = [dict(label=f'World sections {i+1}–{min(i+_SECTIONS_PER_MESH,len(found))}',
                       vertices=sum(x['vertices'] for x in found[i:i+_SECTIONS_PER_MESH]),
                       triangles=sum(x['triangles'] for x in found[i:i+_SECTIONS_PER_MESH]), offset=found[i]['offset'])
                  for i in range(0, len(found), _SECTIONS_PER_MESH)]
        result.append(dict(offset=row['start'], size=row['end']-row['start'], kind='3d model', media='model',
                           layout=LAYOUT, confidence='validated', label=row['name']+' world sections', meshes=listed,
                           nodes=len(listed), triangles=sum(x['triangles'] for x in listed),
                           reason='Bounded tree leaves contain graphics commands whose vertex loads and triangle indices resolve.',
                           preview_settings=dict(format='auto', source='rom', offset=row['start'], mesh=0)))
    return result


def preview(image, asset, selection):
    row = dict(start=asset['offset'], end=asset['offset']+asset['size'])
    found = meshes(level_world.unpack(image, row))
    if not found:
        raise formats.AssetError('The level model bank changed. Rescan ROM Explorer.')
    count = (len(found)+_SECTIONS_PER_MESH-1)//_SECTIONS_PER_MESH
    index = formats.integer(selection.get('mesh', 0), 'Mesh', 0, count-1)
    vertices, faces = [], []
    for section in found[index*_SECTIONS_PER_MESH:(index+1)*_SECTIONS_PER_MESH]:
        for points, triangles in section['parts']:
            first = len(vertices)
            vertices.extend((x,z,-y) for x,y,z in points)
            faces.extend(tuple(first+i for i in face) for face in triangles)
    edges = {tuple(sorted((face[i],face[(i+1)%3]))) for face in faces for i in range(3)}
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges),
                points=sorted({i for face in faces for i in face}),
                surfaces=[dict(indices=face, uv=[[0,0]]*3, colors=[[255,255,255,255]]*3, material=0) for face in faces],
                materials=[], details=dict(format='F3DEX2 world section', vertices=len(vertices), triangles=len(faces)),
                note='A group of world sections; textures and render state are separate.',
                settings=dict(asset['preview_settings'], mesh=index))
