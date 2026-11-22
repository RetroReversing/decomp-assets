"""Local object geometry in size-prefixed members of an offset directory."""

import struct
import zlib

from .. import formats
from . import offset_textures

LAYOUT = 'offset-directory-models'


def unpack(data):
    if len(data) < 6:
        return None
    size = int.from_bytes(data[:4], 'little')
    if not 0 < size <= formats.MAX_BYTES:
        return None
    try:
        decoder = zlib.decompressobj(-15)
        result = decoder.decompress(data[5:], size+1)
    except zlib.error:
        return None
    if not decoder.eof or len(result) != size or len(decoder.unused_data) >= 16:
        return None
    return result


def geometry(data, segment=None):
    if len(data) < 0x58:
        return None
    if segment is None:
        vertices_at, triangles_at = struct.unpack_from('>II', data, 4)
        vertices, triangles, batches = struct.unpack_from('>3H', data, 0x24)
        batch_at = struct.unpack_from('>I', data, 0x38)[0]
    else:
        table = struct.unpack_from('>I', data, 4)[0]
        count = struct.unpack_from('>H', data, 0x1a)[0]
        if not 0 <= segment < count <= 1024 or table < 0x50 or table+count*0x44 > len(data):
            return None
        pos = table+segment*0x44
        vertices_at, triangles_at = struct.unpack_from('>II', data, pos)
        batch_at = struct.unpack_from('>I', data, pos+12)[0]
        vertices, triangles, batches = struct.unpack_from('>3H', data, pos+0x1c)
    if (not 0 < vertices <= 65535 or not 0 < triangles <= 65535 or not 0 < batches <= 4096
            or vertices_at < 0x50 or vertices_at+vertices*10 > len(data)
            or triangles_at < 0x50 or triangles_at+triangles*16 > len(data)
            or batch_at < 0x50 or batch_at+(batches+1)*12 > len(data)):
        return None
    points = [list(struct.unpack_from('>3h', data, vertices_at+index*10)) for index in range(vertices)]
    groups = [struct.unpack_from('>hh', data, batch_at+index*12+2) for index in range(batches+1)]
    if groups[0] != (0, 0) or groups[-1] != (vertices, triangles):
        return None
    faces = []
    for (v0,t0), (v1,t1) in zip(groups,groups[1:]):
        if not 0 <= v0 <= v1 <= vertices or not 0 <= t0 <= t1 <= triangles:
            return None
        for index in range(t0,t1):
            local = data[triangles_at+index*16+1:triangles_at+index*16+4]
            if len(local) != 3 or any(v0+v >= v1 for v in local):
                return None
            faces.append([v0+v for v in local])
    return points, faces


def directories(image, check=lambda: None):
    for base, offsets, _ in offset_textures.catalogs(image, check):
        if len(offsets) <= 30:
            continue
        for section in (26, 28):
            yield from _directory(image, base, offsets, section)


def _directory(image, base, offsets, section):
    start, data_start, data_end = (base+offsets[i] for i in (section, section+1, section+2))
    if not start < data_start < data_end <= len(image) or data_start-start > 0x10000:
        return
    positions = []
    for at in range(start,data_start-3,4):
        value = int.from_bytes(image[at:at+4], 'big')
        if value == 0xffffffff:
            break
        if value % 16 or value > data_end-data_start or positions and value < positions[-1]:
            break
        positions.append(value)
    else:
        return
    if len(positions) >= 17 and positions[0] == 0 and positions[-1] == data_end-data_start:
        yield data_start, data_end, positions, section == 26


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for start, end, offsets, levels in directories(image, check):
        meshes = []
        for index, (a,b) in enumerate(zip(offsets,offsets[1:])):
            if not index%32:
                check()
                progress(dict(phase='Checking cartridge model records', done=index, total=len(offsets)-1))
            data = unpack(image[start+a:start+b])
            if not data:
                continue
            count = int.from_bytes(data[0x1a:0x1c], 'big') if levels and len(data) >= 0x1c else 1
            if count > 1024:
                continue
            for segment in range(count):
                part = segment if levels else None
                mesh = geometry(data, part)
                if mesh:
                    name = f'Level {index}, segment {segment}' if levels else f'Model {index}'
                    meshes.append(dict(name=name, offset=start+a, size=b-a, segment=part,
                                       vertices=len(mesh[0]), triangles=len(mesh[1])))
        if meshes:
            kind = 'level segments' if levels else 'object models'
            result.append(dict(offset=start,size=end-start,kind='3d model',media='model',layout=LAYOUT,
                               confidence='validated',label=f'{len(meshes)} {kind}', meshes=meshes,
                               vertices=sum(m['vertices'] for m in meshes),
                               triangles=sum(m['triangles'] for m in meshes),
                               reason='The offset table, decompressed model headers and vertex batches agree. Geometry is shown without textures.',
                               preview_settings=dict(source='rom',format='auto',offset=start)))
    return result


def preview(image, asset, selection):
    index = formats.integer(selection.get('mesh',0),'Mesh',0,len(asset['meshes'])-1)
    item = asset['meshes'][index]
    start, end = item['offset'], item['offset']+item['size']
    if not 0 <= start < end <= len(image):
        raise formats.AssetError('The model directory changed. Scan ROM Explorer again.')
    data = unpack(image[start:end])
    parsed = geometry(data, item.get('segment')) if data else None
    if not parsed or (len(parsed[0]),len(parsed[1])) != (item['vertices'],item['triangles']):
        raise formats.AssetError('The model record changed. Scan ROM Explorer again.')
    vertices, faces = parsed
    edges = sorted({tuple(sorted((face[i],face[(i+1)%3]))) for face in faces for i in range(3)})
    return dict(media='model',vertices=vertices,triangles=len(faces),edges=edges,
                points=sorted({v for face in faces for v in face}),materials=[],
                surfaces=[dict(indices=face,uv=[[0,0]]*3,colors=[[255,255,255,255]]*3,material=0)
                          for face in faces],
                details=dict(format='Offset directory object model',vertices=len(vertices),triangles=len(faces)),
                settings=dict(asset['preview_settings'],mesh=index))
