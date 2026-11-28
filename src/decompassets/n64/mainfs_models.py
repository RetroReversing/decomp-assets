"""Local FORM geometry in packed main filesystem files.

VTX1 and FAC1 layouts follow the public-domain PartyPlanner64 FORM reader;
object transforms, materials and animation are not reconstructed here.
"""
import math
import struct

from .. import formats
from . import mainfs

LAYOUT = 'mainfs-form-model'


def geometry(data):
    """Decode a complete vertex/face pair, rejecting unsupported face types."""
    if data[:4] != b'FORM':
        return None
    chunks = {}
    at = 8
    while at + 8 <= len(data):
        tag = data[at:at+4]
        at += 4
        if tag == b'HBIN':
            if data[at:at+4] != b'MODE':
                return None
            at += 4
        if at + 4 > len(data):
            return None
        length = int.from_bytes(data[at:at+4], 'big')
        at += 4
        if at + length > len(data):
            return None
        if tag in (b'VTX1', b'FAC1'):
            if tag in chunks:
                return None
            chunks[tag] = data[at:at+length]
        at += length + (length & 1)
    if at != len(data) or b'VTX1' not in chunks or b'FAC1' not in chunks:
        return None
    v, f = chunks[b'VTX1'], chunks[b'FAC1']
    if len(v) < 8 or len(f) < 8:
        return None
    count = int.from_bytes(v[:2], 'big')
    scale = struct.unpack_from('>f', v, 4)[0]
    if not 3 <= count <= 65535 or 8 + 9*count > len(v) or not math.isfinite(scale) or not 0 < scale <= 1e6:
        return None
    vertices = [list(struct.unpack_from('>hhh', v, 8+9*i)) for i in range(count)]
    vertices = [[axis * scale for axis in vertex] for vertex in vertices]
    face_count = int.from_bytes(f[:2], 'big')
    if not 1 <= face_count <= 16384:
        return None
    surfaces = []
    pos = 8
    for _ in range(face_count):
        if pos >= len(f) or f[pos] not in (0x16, 0x35):
            return None
        number = 3 if f[pos] == 0x16 else 4
        pos += 1
        if pos + 12*number + 5 > len(f):
            return None
        entries = [struct.unpack_from('>Hhff', f, pos+12*i) for i in range(number)]
        if any(e[0] >= count or not math.isfinite(e[2]) or not math.isfinite(e[3]) for e in entries):
            return None
        for a, b, c in ([(0, 1, 2)] if number == 3 else [(0, 1, 2), (0, 2, 3)]):
            selected = [entries[a], entries[b], entries[c]]
            surfaces.append(dict(indices=[e[0] for e in selected], uv=[[e[2], e[3]] for e in selected],
                                 colors=[[255, 255, 255, 255]]*3, material=0))
        pos += 12*number + 5
    return vertices, surfaces


def regions(image, *, check=lambda: None, **kwargs):
    root, files = mainfs.find(image, check)
    if not files:
        return []
    result = []
    for i, (directory, index, at) in enumerate(files):
        if not i % 64:
            check()
        try:
            if mainfs.unpack(image, at, mainfs.PEEK)[:4] != b'FORM':
                continue
            parsed = geometry(mainfs.unpack(image, at))
        except (formats.AssetError, struct.error):
            continue
        if not parsed:
            continue
        vertices, surfaces = parsed
        # The filesystem has no end offset for its final member. Do not
        # label the rest of the cartridge as model data.
        following = files[i+1][2] if i+1 < len(files) else min(len(image), at + 8 + int.from_bytes(image[at:at+4], 'big'))
        if following <= at:
            continue
        result.append(dict(offset=at, size=following-at, root=root, directory=directory, file=index,
                           kind='3d model', media='model', layout=LAYOUT, confidence='validated',
                           label=f'FORM geometry {directory}/{index}', vertices=len(vertices), triangles=len(surfaces),
                           meshes=[dict(label='Local geometry', vertices=len(vertices), triangles=len(surfaces))],
                           preview_settings=dict(format='auto', source='rom', offset=at),
                           reason='The bounded filesystem file has consistent vertex and face chunks.'))
    return result


def preview(image, asset, selection):
    formats.integer(selection.get('mesh', 0), 'Model', 0, 0)
    files = mainfs.files(image, asset['root'])
    if not files or (asset['directory'], asset['file'], asset['offset']) not in files:
        raise formats.AssetError('The filesystem changed. Rescan ROM Explorer.')
    parsed = geometry(mainfs.unpack(image, asset['offset']))
    if not parsed:
        raise formats.AssetError('The model changed. Rescan ROM Explorer.')
    vertices, surfaces = parsed
    edges = {tuple(sorted((s['indices'][i], s['indices'][(i+1)%3]))) for s in surfaces for i in range(3)}
    return dict(media='model', vertices=vertices, triangles=len(surfaces), edges=sorted(edges),
                points=sorted({i for s in surfaces for i in s['indices']}), surfaces=surfaces, materials=[],
                details=dict(format='FORM local geometry', vertices=len(vertices), triangles=len(surfaces)),
                note='Local geometry only; object transforms, materials and animation are separate.',
                settings=asset['preview_settings'])
