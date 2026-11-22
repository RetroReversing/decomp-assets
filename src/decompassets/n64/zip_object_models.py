"""Model display lists and vertex arrays in archived relocatable objects."""

import struct

from .. import archives, formats
from . import display_meshes

LAYOUT = 'zip-object-model'
_SECTION = struct.Struct('>10I')
_SYMBOL = struct.Struct('>IIIBBH')


def _objects(data):
    if len(data) < 52 or data[:7] != b'\x7fELF\x01\x02\x01' or struct.unpack_from('>HH', data, 16) != (1, 8):
        return []
    offset = struct.unpack_from('>I', data, 32)[0]
    size, count = struct.unpack_from('>HH', data, 46)
    if size != 40 or not 1 <= count <= 1024 or offset + size*count > len(data):
        return []
    sections = [_SECTION.unpack_from(data, offset+size*i) for i in range(count)]
    symbols = {}
    for section in sections:
        _,kind,_,_,start,length,link,_,_,stride = section
        if kind != 2 or stride != 16 or length % stride or link >= count or start + length > len(data):
            continue
        strings = sections[link]
        if strings[1] != 3 or strings[4] + strings[5] > len(data):
            continue
        names = data[strings[4]:strings[4]+strings[5]]
        for pos in range(start,start+length,stride):
            name,value,extent,info,_,index = _SYMBOL.unpack_from(data,pos)
            if info & 15 != 1 or index >= count or name >= len(names) or not extent:
                continue
            stop = names.find(b'\0',name)
            if stop < 0:
                continue
            label = names[name:stop]
            target = sections[index]
            if target[1] != 1 or value + extent > target[5] or target[4] + target[5] > len(data):
                continue
            if label.endswith((b'_dl', b'_vtx')):
                symbols[label] = (target[4]+value,extent)
    result = []
    for name,(dl,size) in symbols.items():
        if not name.endswith(b'_dl') or (vertex := symbols.get(name[:-3]+b'_vtx')) is None:
            continue
        start, length = vertex
        if dl % 8 or size % 8 or start % 8 or length % 16 or not 0 < length // 16 <= 65536:
            continue
        result.append((dl,dl+size,start,start+length))
    return result


def _geometry(data, obj, check):
    lo,end,vertex,vertex_end = obj
    patched = bytearray(data)
    for at in range(lo,end,8):
        command,address = struct.unpack_from('>II',patched,at)
        if command >> 24 == 1 and address < (vertex_end-vertex)//16:
            struct.pack_into('>I',patched,at+4,address*16)
    meshes, stop = [], 0
    for at in range(lo,end,8):
        if at % 0x10000 == 0:
            check()
        if at < stop or patched[at] != 1:
            continue
        parsed = display_meshes.geometry(patched,at,end,{0:vertex},vertex_end=vertex_end,vertex_flag_mask=0xffff,
                                        extra_state=lambda a,b: a >> 16 == 0x0214 or a >> 24 == 3)
        if parsed:
            stop,vertices,faces = parsed
            meshes.append((at,vertices,faces))
    return meshes


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for member in archives.zip_members(image,check=check):
        if not member['name'].lower().endswith('.o'):
            continue
        try:
            data = archives.member_bytes(image,member)
        except formats.AssetError:
            continue
        for obj in _objects(data):
            found = _geometry(data,obj,check)
            if not found:
                continue
            meshes = [dict(name=f'Mesh {i+1}', descriptor=at, vertices=len(vertices), triangles=len(faces))
                      for i,(at,vertices,faces) in enumerate(found)]
            result.append(dict(offset=member['offset'],size=member['size'],kind='3d model',media='model',
                               layout=LAYOUT,label=member['name'],confidence='validated',member=member,object=obj,
                               reason='Object symbols bound the display list and vertex array; triangle indices agree.',
                               nodes=0,meshes=meshes,vertices=sum(m['vertices'] for m in meshes),
                               triangles=sum(m['triangles'] for m in meshes),
                               preview_settings=dict(source='rom',format='auto',offset=member['offset'])))
    return result


def preview(image, asset, selection):
    slot = formats.integer(selection.get('mesh',0),'Mesh',0,len(asset['meshes'])-1)
    data = archives.member_bytes(image,asset['member'])
    obj = tuple(asset['object'])
    if obj not in _objects(data):
        raise formats.AssetError('The archived model changed. Rescan ROM Explorer.')
    meshes = _geometry(data,obj,lambda:None)
    descriptor = asset['meshes'][slot]['descriptor']
    found = next((mesh for mesh in meshes if mesh[0] == descriptor),None)
    if not found:
        raise formats.AssetError('The model mesh changed. Rescan ROM Explorer.')
    _,vertices,faces = found
    edges = {tuple(sorted((face[i],face[(i+1)%3]))) for face in faces for i in range(3)}
    return dict(media='model',vertices=vertices,triangles=len(faces),edges=sorted(edges),points=list(range(len(vertices))),
                surfaces=[dict(indices=face,uv=[[0,0]]*3,colors=[[255,255,255,255]]*3,material=0) for face in faces],
                materials=[],details=dict(format='Archived display-list mesh',vertices=len(vertices),triangles=len(faces)),
                note='Local geometry; texture bindings and runtime placement are separate.',
                settings=dict(source='rom',format='auto',offset=asset['offset'],mesh=slot))
