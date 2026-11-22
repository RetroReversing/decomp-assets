"""Indexed model nodes stored in named archive members."""

import struct

from .. import formats
from . import lzhuf, wad_resources

LAYOUT = 'wad-node-model'
_EXTENSIONS = frozenset(('TMD', 'GMD', 'K2', 'K3', 'K4', 'K5'))


def _model(data):
    if len(data) < 12 or data[:4] != b'2KMD':
        return None
    count = struct.unpack_from('>I', data, 4)[0]
    if not 1 <= count <= 256 or 8 + count * 4 + 4 > len(data):
        return None
    nodes = []
    for i in range(count):
        at = struct.unpack_from('>I', data, 8 + 4*i)[0]
        if not 8 + count*4 <= at <= len(data) - 24:
            return None
        vertices, triangles, vo, to, _, _ = struct.unpack_from('>6I', data, at)
        if (not 1 <= vertices <= 8192 or not 0 <= triangles <= 16384
                or vo < 24 or to < 24 or at + vo + 16*vertices > len(data)
                or at + to + 6*triangles > len(data)):
            return None
        faces = list(struct.iter_unpack('>3H', data[at+to:at+to+6*triangles]))
        if any(max(face) >= vertices for face in faces):
            return None
        nodes.append((at + vo, vertices, faces))
    return nodes if any(faces for _,_,faces in nodes) else None


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result, seen = [], set()
    for name, offset, _, size, decoded_size in wad_resources._members(image, check):
        if name.rsplit('.', 1)[-1] not in _EXTENSIONS or offset in seen:
            continue
        seen.add(offset)
        source = image[offset:offset+size]
        try:
            data = lzhuf.unpack(source, decoded_size, check) if size != decoded_size else source
        except formats.AssetError:
            continue
        nodes = _model(data)
        if not nodes:
            continue
        meshes = [dict(name=f'Node {i+1}', node=i, vertices=count, triangles=len(faces))
                  for i,(_,count,faces) in enumerate(nodes) if faces]
        result.append(dict(offset=offset, size=size, kind='3d model', media='model', layout=LAYOUT,
                           label=name, confidence='validated', decoded_size=decoded_size,
                           reason='Archive extent, node records and triangle indices agree.',
                           nodes=len(nodes), meshes=meshes, vertices=sum(m['vertices'] for m in meshes),
                           triangles=sum(m['triangles'] for m in meshes),
                           preview_settings=dict(source='rom', format='auto', offset=offset)))
    return result


def preview(image, asset, selection):
    index = formats.integer(selection.get('mesh', 0), 'Mesh', 0, len(asset['meshes'])-1)
    source = image[asset['offset']:asset['offset']+asset['size']]
    data = lzhuf.unpack(source, asset['decoded_size']) if asset['size'] != asset['decoded_size'] else source
    nodes = _model(data)
    if nodes is None:
        raise formats.AssetError('The model changed. Rescan ROM Explorer.')
    at,count,faces = nodes[asset['meshes'][index]['node']]
    vertices = [row[:3] for row in struct.iter_unpack('>hhhHhhBBBB', data[at:at+16*count])]
    edges = {tuple(sorted((face[i],face[(i+1)%3]))) for face in faces for i in range(3)}
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges),
                points=list(range(count)),
                surfaces=[dict(indices=face, uv=[[0,0]]*3, colors=[[255,255,255,255]]*3, material=0)
                          for face in faces], materials=[],
                details=dict(format='Indexed model node', vertices=count, triangles=len(faces)),
                note='Local node geometry; hierarchy, animation and materials are separate.',
                settings=dict(format='auto', source='rom', offset=asset['offset'], mesh=index))
