"""Models described by local mesh pointers in named cartridge members."""

import re
import struct

from .. import formats
from . import display_meshes, named_resources

LAYOUT = 'named-resource-meshes'
_HEADER = struct.Struct('>IIHHII')
_ROW = struct.Struct('>II4H')
_MAGIC = re.compile(rb'\0\0d\xc8')


def _matrix(word, value):
    return word & 0xfffffff8 == 0xda380000 and value >> 24 in (8, 9, 10, 11) and value & 63 == 0


def _meshes(data):
    result = []
    finish = 0
    for match in _MAGIC.finditer(data):
        base = match.start()
        if base%8 or base < finish or base+_HEADER.size > len(data):
            continue
        _, size, count, _, table, name = _HEADER.unpack_from(data, base)
        if not 0 < count <= 256 or not _HEADER.size <= table <= table+count*_ROW.size <= name < size <= len(data)-base:
            continue
        local = data[base:base+size]
        end = local.find(b'\0', name, min(name+48, size))
        if end <= name or not all(32 <= byte < 127 for byte in local[name:end]):
            continue
        label = local[name:end].decode('ascii')
        first = len(result)
        for start, _, *_ in _ROW.iter_unpack(local[table:table+count*_ROW.size]):
            if not _HEADER.size <= start < table:
                continue
            parsed = display_meshes.geometry(local, start, table, {12: 0},
                                             extra_state=_matrix, vertex_end=table)
            if parsed:
                last, vertices, faces = parsed
                result.append(dict(name=f'{label} · Mesh {len(result)-first+1}', offset=base+start,
                                   size=last-start, vertex_base=base, vertex_end=base+table,
                                   vertices=len(vertices), triangles=len(faces)))
        finish = base+size
    return result


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for name, packed, start, end in named_resources.members(image, check):
        check()
        if not packed:
            continue
        data = named_resources.unpack(image[start:end])
        if data is None or not (meshes := _meshes(data)):
            continue
        result.append(dict(offset=start, size=end-start, kind='3d model', media='model', confidence='validated',
                           layout=LAYOUT, label=name, nodes=len(meshes), meshes=meshes,
                           vertices=sum(mesh['vertices'] for mesh in meshes),
                           triangles=sum(mesh['triangles'] for mesh in meshes),
                           reason='Named model directories point to closed F3DEX2 lists and local vertex data.',
                           preview_settings=dict(format='auto', source='rom', offset=start)))
    return result


def preview(image, asset, selection):
    start, size = asset['offset'], asset['size']
    data = named_resources.unpack(image[start:start+size])
    if data is None or not (meshes := _meshes(data)):
        raise formats.AssetError('The compressed model directory changed. Rescan ROM Explorer.')
    index = formats.integer(selection.get('mesh', 0), 'Mesh', 0, len(meshes)-1)
    mesh = meshes[index]
    local = dict(mesh, address_maps=[(12, mesh['vertex_base'])], label=mesh['name'],
                 preview_settings=dict(asset['preview_settings'], mesh=index))
    return display_meshes.preview(data, local, selection, extra_state=_matrix)
