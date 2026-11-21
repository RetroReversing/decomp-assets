"""Textures in eight-byte asset directories with size-prefixed Rare deflate."""

import re
import struct
import zlib
from itertools import pairwise

from .. import formats
from ..formats import AssetError
from .display_meshes import geometry
from .rare_models import MAX_ASSETS, MAX_EXPANDED, MAX_MODEL, MODEL, TYPES

TEXTURES = 'rare-directory-textures'
MESH = 'rare-directory-mesh'


def directories(image,check):
    for hit in re.finditer(rb'\x00\x00..\xff\xff\xff\xff\x00\x00\x00\x00\x00\x01',image,re.S):
        check()
        at = hit.start()
        count = int.from_bytes(image[at:at+4],'big')
        base = at+8+8*count
        if at%4 or not 16 <= count <= MAX_ASSETS or base > len(image):
            continue
        rows = list(struct.iter_unpack('>IHH',image[at+8:base]))
        if (base+rows[-1][0] > len(image) or any(flags not in (0,1) or kind>4 for _,flags,kind in rows)
                or any(second[0] < first[0] for first,second in pairwise(rows))):
            continue
        packed = [(index,base+offset,base+following[0])
                  for index,((offset,flags,_),following) in enumerate(pairwise(rows))
                  if flags and offset < following[0]]
        if len(packed) >= 16 and all(image[start:start+2] == b'\x11\x72' for _,start,_ in packed):
            yield packed


def inflate(data):
    if len(data) < 8 or data[:2] != b'\x11\x72':
        return None
    size = int.from_bytes(data[2:6],'big')
    if not 0 < size <= MAX_MODEL:
        return None
    stream = zlib.decompressobj(-15)
    try:
        out = stream.decompress(data[6:],size+1)
    except zlib.error:
        return None
    return out if stream.eof and len(out) == size and len(stream.unused_data) <= 15 else None


def textures(model):
    if model[:4] != MODEL or len(model) < 0x38:
        return None
    setup = int.from_bytes(model[8:10],'big')
    if setup < 0x38 or setup+8 > len(model):
        return None
    size,count = struct.unpack_from('>IH',model,setup)
    data = setup+8+16*count
    end = setup+size
    if not 0 < count <= 256 or not data <= end <= len(model):
        return None
    items = []
    previous_end = data
    for index in range(count):
        offset,kind,width,height = struct.unpack_from('>IH2xBB',model,setup+8+16*index)
        if kind&0x7fff not in TYPES or not width or not height:
            return None
        fmt,entries,bits = TYPES[kind&0x7fff]
        start = data+offset
        pixels = (width*bits+7)//8*height
        finish = start+2*entries+pixels
        if start < previous_end or finish > end:
            return None
        previous_end = finish
        settings = dict(format=fmt,width=width,height=height,offset=start+2*entries)
        if entries:
            settings.update(palette_offset=start,palette_format='rgba5551-be')
        items.append(dict(preview_settings=settings,frames=1,palettes=1 if entries else 0,
                          palette_entries=[entries] if entries else [],palette_offsets=[start] if entries else [],
                          levels=[dict(width=width,height=height,offset=0)]))
    return items


def _state(word, address):
    # Segment 3 selects renderer state supplied by the engine. The matrix pop
    # also leaves the local vertex and triangle indices intact.
    return (word == 0x06000000 and address >> 24 == 3) or (word == 0xbd000000 and address == 0)


def meshes(model):
    if model[:4] != MODEL or len(model) < 0x38:
        return []
    display, vertices = struct.unpack_from('>II', model, 12)
    if not 0x38 <= display <= len(model)-8 or not 0x38 <= vertices <= len(model)-24:
        return []
    count, reserved = struct.unpack_from('>II', model, display)
    vertex_count = struct.unpack_from('>H', model, vertices+20)[0]
    vertex_start = vertices+24
    vertex_end = vertex_start+16*vertex_count
    start, end = display+8, display+8+8*count
    if reserved or not 0 < count <= 65536 or end > len(model) or not vertex_count or vertex_end > len(model):
        return []
    results = []
    for command in range(start, end, 8):
        word, address = struct.unpack_from('>II', model, command)
        if word >> 24 == 4:
            length = ((word >> 10)&63)*16
            if address >> 24 != 1 or (address & 0xffffff)+length > vertex_end-vertex_start:
                return []
        if word != 0xb8000000 or address:
            continue
        parsed = geometry(model, start, command+8, {1: vertex_start}, extra_state=_state)
        if parsed:
            results.append(parsed[1:])
        start = command+8
    return results


def mesh_preview(model, asset, selection):
    parts = meshes(model)
    if not parts:
        raise AssetError('The model display lists changed. Scan ROM Explorer again.')
    index = formats.integer(selection.get('mesh',0),'Mesh',0,len(parts)-1)
    vertices, faces = parts[index]
    edges = sorted({tuple(sorted((face[i], face[(i+1)%3]))) for face in faces for i in range(3)})
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=edges,
                points=sorted({i for face in faces for i in face}), materials=[],
                surfaces=[dict(indices=face, uv=[[0,0]]*3, colors=[[255,255,255,255]]*3, material=0)
                          for face in faces],
                details=dict(format='Rare F3DEX model', vertices=len(vertices), triangles=len(faces)),
                settings={**asset['preview_settings'], 'mesh':index})

def regions(image, *, check=lambda: None, progress=lambda _: None):
    results = []
    expanded = 0
    for directory in directories(image,check):
        for index,at,end in directory:
            if not index%64:
                check()
                progress(dict(phase='Checking Rare asset members',done=index,total=directory[-1][0]+1))
            model = inflate(image[at:end])
            if model is None:
                continue
            expanded += len(model)
            if expanded > MAX_EXPANDED:
                return results
            parts = meshes(model)
            if parts:
                results.append(dict(offset=at,size=end-at,kind='3d model',media='model',layout=MESH,
                                    label=f'Model {index}',confidence='validated',asset_index=index,
                                    vertices=sum(len(vertices) for vertices,_ in parts),
                                    triangles=sum(len(faces) for _,faces in parts),
                                    meshes=[dict(name=f'Mesh {number}',vertices=len(vertices),triangles=len(faces))
                                            for number,(vertices,faces) in enumerate(parts,1)],
                                    reason='The model display lists reference bounded local vertices and triangles.',
                                    preview_settings=dict(source='rom',format='auto',offset=at)))
            if not (items := textures(model)):
                continue
            first = items[0]
            results.append(dict(offset=at,size=end-at,kind='image',layout=TEXTURES,confidence='validated',
                                label=f'Model {index} textures',asset_index=index,textures=items,frames=1,
                                palettes=first['palettes'],levels=first['levels'],
                                reason='The checked asset slot expands to a model with bounded texture and palette records.',
                                preview_settings={**first['preview_settings'],'source':'rom','offset':at}))
    return results


def preview(image,asset,selection):
    at = asset['offset']
    model = inflate(image[at:at+asset['size']])
    if model and asset['layout'] == MESH:
        return mesh_preview(model,asset,selection)
    items = model and textures(model)
    if not items:
        raise AssetError('The model texture setup changed. Scan ROM Explorer again.')
    index = formats.integer(selection.get('texture',0),'Texture',0,len(items)-1)
    result = formats.preview(model,items[index]['preview_settings'])
    result['settings'] = dict(source='rom',format='auto',offset=at,texture=index)
    result['decoded'] = dict(codec='Rare deflate',bytes=len(model),block_offset=at,member=f'texture {index}')
    return result
