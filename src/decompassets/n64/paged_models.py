"""Mesh records in paged N64 resource directories."""

import math
import re
import struct
from itertools import islice, pairwise

from .. import formats
from . import packed_anim

LAYOUT = 'paged-resource-mesh'
_ARCHIVE = re.compile(rb'\0\x03[\x01-\x20]\0\0\0\0\x08')
_NAME = re.compile(rb'[A-Z0-9_+ -]{1,8}')
_ENTRY = struct.Struct('>8sIII')
_PAGE_ROWS = 256
_PAGE = _PAGE_ROWS*_ENTRY.size
_FACE = struct.Struct('>6H')
_VERTEX = struct.Struct('>3fI')


def _rows(image, base, check):
    pages = image[base+2]
    cursor = base+8
    records, directories = [], []
    for index in range(pages):
        check()
        end = cursor+_PAGE+4
        if not base+8 <= cursor < end <= len(image) or directories and cursor < directories[-1][1]:
            return None
        directories.append((cursor,end))
        for name, kind, size, relative in _ENTRY.iter_unpack(image[cursor:end-4]):
            if not any(name):
                if index != pages-1 or kind or size or relative:
                    return None
                continue
            name = name.rstrip(b'\0')
            at = base+relative
            if (not _NAME.fullmatch(name) or not 0 < kind <= 32
                    or not base+8 <= at < at+size <= len(image) or relative%2):
                return None
            records.append((at,at+size,kind,name.decode('ascii')))
        next_page, = struct.unpack_from('>I',image,end-4)
        if bool(next_page) != (index+1<pages):
            return None
        cursor = base+next_page
    records.sort()
    if len(records) < 4 or any(left[1]>right[0] for left,right in pairwise(records)):
        return None
    if any(a < high and low < b for a,b,_,_ in records for low,high in directories):
        return None
    return records


def _geometry(image, start, end, check):
    if start+4 > end:
        return None
    size, = struct.unpack_from('>I',image,start)
    if not 60 <= size <= formats.MAX_BYTES:
        return None
    raw = packed_anim._unpack(image[start+4:end],size,check)
    if raw is None:
        return None
    faces, count, normals = struct.unpack_from('>3H',raw)
    vertex_start = 60+56*faces
    vertex_end = vertex_start+16*count
    if not (0 < faces <= 8192 and 3 <= count <= 8192 and 0 < normals <= 8192 and vertex_end <= size):
        return None
    vertices = [values[:3] for values in _VERTEX.iter_unpack(raw[vertex_start:vertex_end])]
    if not all(math.isfinite(value) for point in vertices for value in point):
        return None
    triangles = []
    for offset in range(60,vertex_start,56):
        face = _FACE.unpack_from(raw,offset)
        if max(face[:3])>=count or max(face[3:])>=normals:
            return None
        triangles.append(face[:3])
    return (vertices,triangles) if any(len(set(face))==3 for face in triangles) else None


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for match in islice(_ARCHIVE.finditer(image),128):
        check()
        records = _rows(image,match.start(),check) if match.start()%2==0 else None
        if records is None:
            continue
        for offset, end, kind, name in records:
            check()
            if kind == 11 and offset%4:
                frames = packed_anim.frames(image,offset,end,check)
                for index, frame in enumerate(frames,1):
                    result.append({**frame,'label':f'{name} frame {index}'})
            if kind not in (2,5):
                continue
            geometry = _geometry(image,offset,end,check)
            if geometry:
                vertices, triangles = geometry
                result.append(dict(offset=offset,size=end-offset,kind='3d model',media='model',layout=LAYOUT,
                                   label=name,confidence='validated',vertices=len(vertices),triangles=len(triangles),
                                   reason='The native resource directory bounds the compressed model. All face indices resolve.',
                                   preview_settings=dict(format='auto',source='rom',offset=offset)))
    return result


def preview(image, asset, selection):
    start, size = asset['offset'], asset['size']
    geometry = _geometry(image,start,start+size,lambda: None)
    if not geometry:
        raise formats.AssetError('The paged archive mesh changed. Rescan ROM Explorer.')
    vertices, faces = geometry
    edges = {tuple(sorted((face[i],face[(i+1)%3]))) for face in faces for i in range(3)}
    return dict(media='model',vertices=vertices,triangles=len(faces),edges=sorted(edges),
                points=sorted({i for face in faces for i in face}),
                surfaces=[dict(indices=face,uv=[[0,0]]*3,colors=[[255]*4]*3,material=0) for face in faces],
                materials=[],details=dict(format=asset['label'],vertices=len(vertices),triangles=len(faces)),
                note='Local model positions and faces. Motion and material data are separate.',
                settings=asset['preview_settings'])
