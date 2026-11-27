"""Bounded local geometry in checksum-verified RNC-wrapped PGD files."""
import re
import struct

from .. import formats
from . import rnc_shpn_images

LAYOUT = 'rnc-pgd-model'
_MAX_EXPANDED = 64 * 1024 * 1024


def _geometry(data):
    if len(data) < 0xa4 or data[:4] != b'PGD\x01':
        return None
    nodes, materials, _, faces, vertices = struct.unpack_from('>5I', data, 0x24)
    face_end, vertex_start = struct.unpack_from('>I4xI', data, 0x48)
    base = 0x60 + nodes * 0x44
    if (not 0 < nodes <= 128 or not 0 < materials <= 256 or not 0 < faces <= 20000
            or not 0 < vertices <= 20000 or face_end != 0x3c + 8 * faces
            or vertex_start < face_end or base + vertex_start + 6 * vertices > len(data)):
        return None
    triangles = [struct.unpack_from('>4H', data, base + 0x3c + i * 8) for i in range(faces)]
    if any(max(face[:3]) >= vertices or face[3] >= materials for face in triangles):
        return None
    points = [struct.unpack_from('>3h', data, base + vertex_start + i * 6) for i in range(vertices)]
    return points, [face[:3] for face in triangles]


def regions(image, *, check=lambda: None, **kwargs):
    found, expanded = [], 0
    for match in re.finditer(b'RNC[\x01\x02]', image):
        check()
        start = match.start()
        if start + 18 > len(image):
            continue
        size, packed = struct.unpack_from('>II', image, start + 4)
        extent = packed + 18
        if not 0 < size <= formats.MAX_BYTES or not 0 < packed <= formats.MAX_BYTES or start + extent > len(image):
            continue
        if expanded + size > _MAX_EXPANDED:
            break
        expanded += size
        data = rnc_shpn_images._unpack(image, start, extent)
        geometry = _geometry(data) if data else None
        if not geometry:
            continue
        points, faces = geometry
        found.append(dict(offset=start, size=extent, kind='3d model', media='model', layout=LAYOUT,
                          label='RNC PGD local mesh', confidence='validated', vertices=len(points), triangles=len(faces),
                          reason='RNC checksums, bounded mesh arrays and every triangle index passed validation.',
                          preview_settings=dict(format='auto', source='rom', offset=start)))
    return found


def preview(image, asset, selection):
    data = rnc_shpn_images._unpack(image, asset['offset'], asset['size'])
    geometry = _geometry(data) if data else None
    if not geometry:
        raise formats.AssetError('The compressed model changed. Scan ROM Explorer again.')
    vertices, faces = geometry
    edges = {tuple(sorted((face[i], face[(i+1) % 3]))) for face in faces for i in range(3)}
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges),
                points=sorted({i for face in faces for i in face}),
                surfaces=[dict(indices=face, uv=[[0, 0]] * 3, colors=[[255, 255, 255, 255]] * 3, material=0)
                          for face in faces], materials=[],
                details=dict(format=asset['label'], vertices=len(vertices), triangles=len(faces)),
                note='Local geometry only; scene placement, materials and animation are separate.',
                settings=asset['preview_settings'])
