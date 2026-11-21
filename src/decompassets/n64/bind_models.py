"""Read A3D positions and material-batched triangles in BIND archives."""

import math
import re
import struct

from .. import formats
from ..formats import AssetError
from . import bind

LAYOUT = 'bind-a3d'
_NAME = re.compile(rb'[A-Za-z0-9_][ -~]*\.A3D', re.IGNORECASE)
_MAX_FACES = 32768


def _geometry(data):
    if len(data) < 64:
        return None
    size, packed_name, count = struct.unpack_from('>I32sI',data)
    name = packed_name.split(b'\0')[0]
    at = 40+16*count
    if size != len(data) or not _NAME.fullmatch(name) or not 3 <= count <= 4096 or at+24 > size:
        return None
    positions = []
    for x,y,z,unused in struct.iter_unpack('>4f',data[40:at]):
        if unused or not all(math.isfinite(value) and abs(value) < 1e8 for value in (x,y,z)):
            return None
        positions.append((x,y,z))
    total, textured, unknown, material_count, batch_count, flags = struct.unpack_from('>6I',data,at)
    at += 24
    if (not 0 < total <= _MAX_FACES or textured > total or unknown or flags
            or material_count > 256 or batch_count > 1024):
        return None

    faces, materials = [], []

    def batch(cursor, material, limit):
        triangles, mapped = struct.unpack_from('>2I',data,cursor)
        begin = cursor+8+4*mapped
        end = begin+48*triangles
        if not 0 < triangles <= limit-len(faces) or not 0 < mapped <= count or end > size:
            raise ValueError
        remap = struct.unpack_from(f'>{mapped}I',data,cursor+8)
        if max(remap) >= count:
            raise ValueError
        for face in range(begin,end,48):
            corners = [struct.unpack_from('>Ihh',data,corner) for corner in range(face,face+48,16)]
            if any(index >= mapped for index,_,_ in corners):
                raise ValueError
            faces.append((tuple(remap[index] for index,_,_ in corners),material))
        return end

    batches = 0
    try:
        for material in range(material_count):
            texture, _, _, _, groups, _ = struct.unpack_from('>32s5I',data,at)
            if not 0 < groups <= batch_count-batches:
                return None
            at += 52
            batches += groups
            materials.append(texture.split(b'\0')[0].decode('ascii'))
            for _ in range(groups):
                at = batch(at,material,textured)
        if len(faces) != textured or batches != batch_count:
            return None
        if total > textured:
            untextured, _, groups, _ = struct.unpack_from('>4I',data,at)
            if untextured != total-textured or not 0 < groups <= 256:
                return None
            at += 16
            for _ in range(groups):
                at = batch(at,-1,total)
    except (ValueError, struct.error):
        return None
    if len(faces) != total or size-at not in (2,18,22) or any(data[at:]):
        return None
    return name.decode('ascii'),positions,faces,materials


def asset(data, member):
    if not (geometry := _geometry(data)):
        return None
    label, positions, faces, _ = geometry
    return dict(offset=member.offset,size=member.size,kind='3d model',media='model',layout=LAYOUT,label=label,
                confidence='validated',vertices=len(positions),triangles=len(faces),
                reason='The PACK member expands to an A3D model with bounded material batches and vertex remaps.',
                preview_settings=dict(format='auto',source='rom',offset=member.offset))


def preview(image, asset, selection):
    at = asset['offset']
    formats.integer(selection.get('mesh',0),'Mesh',0,0)
    geometry = _geometry(bind.unpack(image[at:at+asset['size']]))
    if geometry is None:
        raise AssetError('The BIND model changed. Scan ROM Explorer again.')
    label, vertices, faces, textures = geometry
    edges = {tuple(sorted((face[i],face[(i+1)%3]))) for face,_ in faces for i in range(3)}
    return dict(media='model',vertices=vertices,edges=sorted(edges),triangles=len(faces),
                materials=[dict(name=texture) for texture in textures],
                surfaces=[dict(indices=face,uv=[[0,0]]*3,colors=[[255,255,255,255]]*3,material=material)
                          for face,material in faces],
                details=dict(format='A3D',name=label,vertices=len(vertices),triangles=len(faces)),
                settings={**asset['preview_settings'],'mesh':0})
