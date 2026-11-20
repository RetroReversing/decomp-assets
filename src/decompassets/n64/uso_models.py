"""Read relocated USO polygon shapes with independently bounded geometry arrays."""

import re
import struct
from itertools import islice

from .. import formats
from .uso_textures import _MAGIC, _NAME, _SECTION, _section

_COMMAND = struct.Struct('>HH')
_VERTEX = struct.Struct('>3h')
_FACE = struct.Struct('>4H')
_WORD = struct.Struct('>I')
_SHAPE = re.compile(rb'\x00\x02\x00\x1b')
_MAX_EXPANDED = 24 * 1024 * 1024
_MAX_VERTICES = 16384
_MAX_TRIANGLES = 32768


def _module(image, offset):
    module = offset+40
    if image[module:module+4] != _MAGIC:
        return None
    sections = {}
    at = module+4
    for _ in range(12):
        if at+_SECTION.size > len(image):
            return None
        kind = _WORD.unpack_from(image, at)[0]
        if kind not in range(1, 12) or kind in sections:
            return None
        span = _section(image, at, kind)
        if span is None:
            return None
        sections[kind] = span
        at = span[1]
        if kind == 11:
            return (sections, at) if span[0] == span[1] and {1, 3, 6} <= sections.keys() else None
    return None


def _inputs(image, sections):
    start, end = sections[6]
    raw = image[start:end]
    if raw.startswith(b'Yay0'):
        raw, _ = formats.unpack(raw)
    symbols = image[slice(*sections[1])]
    relocation = image[slice(*sections[3])]
    if len(symbols) % _SECTION.size or len(relocation) % _SECTION.size:
        return raw, {}
    offsets = [value for _, value, _ in _SECTION.iter_unpack(symbols)]
    links = {}
    for reference, slot, mode in _SECTION.iter_unpack(relocation):
        idx = reference//16
        if mode != 1 or reference % 16 != 4 or idx >= len(offsets) or slot+4 > len(raw):
            continue
        target = offsets[idx] + _WORD.unpack_from(raw, slot)[0]
        if target < len(raw):
            links[slot] = target
    return raw, links


def _geometry(raw, links, at):
    arrays = {}
    for _ in range(64):
        if not 0 <= at <= len(raw)-4:
            return None
        words, opcode = _COMMAND.unpack_from(raw, at)
        if opcode == 2 and words == 0:
            break
        end = at+4+words*4
        if not 1 <= opcode <= 40 or words > 16 or end > len(raw):
            return None
        if opcode in (27, 28, 32):
            if words != 2 or opcode in arrays or at+8 not in links:
                return None
            arrays[opcode] = (links[at+8], _WORD.unpack_from(raw, at+4)[0])
        at = end
    else:
        return None
    if 27 not in arrays or 28 not in arrays:
        return None
    vertex, vertices = arrays[27]
    face, faces = arrays[28]
    v_end, f_end = vertex+vertices*_VERTEX.size, face+faces*_FACE.size
    if (not 3 <= vertices <= _MAX_VERTICES or not 1 <= faces <= _MAX_TRIANGLES
            or max(v_end, f_end) > len(raw) or not (v_end <= face or f_end <= vertex)):
        return None
    remap = None
    index_count = vertices
    if 32 in arrays:
        remap_at, index_count = arrays[32]
        remap_end = remap_at + index_count*_VERTEX.size
        if (not vertices <= index_count <= _MAX_VERTICES or remap_end > len(raw)
                or not (remap_end <= vertex or v_end <= remap_at)
                or not (remap_end <= face or f_end <= remap_at)):
            return None
        remap = [position for position, _, _ in struct.iter_unpack('>Hhh', raw[remap_at:remap_end])]
        if max(remap) >= vertices:
            return None
    for _, a, b, c in _FACE.iter_unpack(raw[face:f_end]):
        if max(a, b, c) >= index_count:
            return None
    return vertex, v_end, face, f_end, remap, vertices, faces


def _read(image, offset):
    module = _module(image, offset)
    if module:
        sections, end = module
        raw, links = _inputs(image, sections)
        return raw, links, end
    return b'', {}, offset


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    expanded = 0
    for file in islice(_NAME.finditer(image), 1024):
        check()
        offset = file.start()
        module = _module(image, offset)
        if not module:
            continue
        start, end = module[0][6]
        size = _WORD.unpack_from(image, start+4)[0] if end-start >= 16 and image[start:start+4] == b'Yay0' else end-start
        if not 0 < size <= formats.MAX_BYTES or expanded+size > _MAX_EXPANDED:
            continue
        expanded += size
        try:
            sections, end = module
            raw, links = _inputs(image, sections)
        except formats.AssetError:
            continue
        meshes = []
        for match in islice(_SHAPE.finditer(raw), 2048):
            check()
            at = match.start()
            if at+8 in links and (geometry := _geometry(raw, links, at)):
                vertices, faces = geometry[-2:]
                meshes.append(dict(descriptor=at, vertices=vertices, triangles=faces,
                                   name=f'Shape at 0x{at:X}'))
        if meshes:
            result.append(dict(offset=offset, size=end-offset, label=file[1].decode(), kind='3d model',
                               media='model', layout='uso-polygon-models', confidence='validated', meshes=meshes,
                               vertices=meshes[0]['vertices'], triangles=meshes[0]['triangles'],
                               reason='USO relocations resolve signed vertex and bounded triangle tables.',
                               preview_settings=dict(format='auto', source='rom', offset=offset)))
    return result


def preview(image, asset, selection):
    raw, links, _ = _read(image, asset['offset'])
    index = formats.integer(selection.get('mesh', 0), 'Mesh', 0, len(asset['meshes'])-1)
    geometry = _geometry(raw, links, asset['meshes'][index]['descriptor'])
    if geometry is None:
        raise formats.AssetError('The USO polygon geometry changed. Rescan the ROM.')
    start, end, first, last, remap, count, total = geometry
    vertices = list(_VERTEX.iter_unpack(raw[start:end]))
    faces = [(a,b,c) for _,a,b,c in _FACE.iter_unpack(raw[first:last])]
    if remap is not None:
        faces = [tuple(remap[index] for index in face) for face in faces]
    edges = {tuple(sorted((face[i], face[(i+1)%3]))) for face in faces for i in range(3)}
    surfaces = [dict(indices=face, uv=[[0,0]]*3, colors=[[255,255,255,255]]*3, material=0) for face in faces]
    return dict(media='model', vertices=vertices, triangles=total, edges=sorted(edges), points=list(range(count)),
                surfaces=surfaces, materials=[], details=dict(format='USO polygon shape', vertices=count, triangles=total),
                note='Local geometry preview. Material binding and scene transforms are separate.',
                settings={**asset['preview_settings'], 'mesh':index})
