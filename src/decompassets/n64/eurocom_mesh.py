"""Read the validated geometry subset of indexed Eurocom mesh commands."""

import math
import struct

from ..formats import AssetError, integer
from . import edl

DESCRIPTOR = struct.Struct('>IHHIHHIHHIHH')
VERTEX = struct.Struct('>3f')


def _component(image, at, size):
    if not 0 <= at <= len(image)-size or size > edl.LIMIT:
        raise AssetError('Eurocom mesh component is outside the image.')
    if edl.header(image, at) is None:
        return image[at:at+size]
    result = edl.unpack(image, at)
    if len(result) != size:
        raise AssetError('Eurocom mesh component has the wrong decoded size.')
    return result


def mesh(image, base, relative):
    at = base + relative
    if not base <= at <= len(image)-DESCRIPTOR.size or at % 4:
        return None
    pos, vertices, _, _, colors, _, _, coords, _, commands, size, _ = DESCRIPTOR.unpack_from(image, at)
    if not vertices or not size or not pos or not commands or not colors or not coords:
        return None
    try:
        data = _component(image, base+commands, size)
    except AssetError:
        return None

    loaded = []
    faces = []
    index = 0
    while index < size:
        opcode = data[index]
        index += 1
        if opcode == 12:
            return (pos, vertices, faces) if faces and index == size else None
        if opcode in (10, 11):
            index += 1
            continue
        if opcode in (0, 1):
            if index == size:
                return None
            count = data[index]
            width = 3 if opcode == 0 else 6
            start = index+1
            index = start+width*count
            if not 1 <= count <= 32 or index > size:
                return None
            loaded = []
            for j in range(start,index,width):
                if width == 3:
                    p,t,c = data[j:j+3]
                else:
                    p,t,c = struct.unpack_from('>3H',data,j)
                if p >= vertices or t >= coords or c >= colors:
                    return None
                loaded.append(p)
            continue
        if opcode == 9:
            index += 3
            continue
        if opcode not in (4, 5, 6, 7, 8):
            return None
        if opcode == 4:
            count = 1
        else:
            index += {5:0, 6:2, 7:1, 8:3}[opcode]
            if index >= size:
                return None
            count = data[index]
            index += 1
        stop = index+3*count
        if stop > size:
            return None
        for tri in range(index,stop,3):
            a,b,c = data[tri:tri+3]
            if max(a,b,c) >= len(loaded):
                return None
            faces.append([loaded[a],loaded[b],loaded[c]])
        index = stop
    return None


def preview(image, asset, selection):
    index = integer(selection.get('mesh',0),'Mesh',0,len(asset['meshes'])-1)
    info = asset['meshes'][index]
    base = asset['archive_base']
    parsed = mesh(image,base,info['descriptor'])
    if parsed is None:
        raise AssetError('The Eurocom mesh layout changed. Rescan ROM Explorer.')
    pos, count, faces = parsed
    data = _component(image,base+pos,count*VERTEX.size)
    vertices = list(VERTEX.iter_unpack(data))
    if not all(math.isfinite(q) for point in vertices for q in point):
        raise AssetError('The mesh contains non-finite coordinates.')
    edges = {tuple(sorted((face[i],face[(i+1)%3]))) for face in faces for i in range(3)}
    surfaces = [dict(indices=face, uv=[[0,0]]*3, colors=[[255,255,255,255]]*3, material=0) for face in faces]
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges),
                points=list(range(count)), surfaces=surfaces, materials=[],
                details=dict(format='Eurocom mesh', vertices=count, triangles=len(faces)),
                note='Local mesh geometry. Placement, texture bindings and runtime draw modes are separate.',
                settings=dict(format='auto', source='rom', offset=asset['offset'], mesh=index))
