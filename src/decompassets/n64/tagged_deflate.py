"""Media from a tagged cartridge directory with size-prefixed raw DEFLATE."""

import re
import struct
import zlib

from .. import formats

IMAGE = 'tagged-deflate-image'
MODEL = 'tagged-deflate-model'
_ROW = struct.Struct('>16s4s5I')
_TEXTURE = struct.Struct('>II4H')
_VERTEX = struct.Struct('>3hH2h4B')
_BATCH = struct.Struct('>6H')
_NAME = re.compile(rb'[a-zA-Z0-9_-]{1,16}')
_FIRST = re.compile(rb'MESH|TXTR|SPRT')
_KINDS = frozenset((b'MESH', b'TXTR', b'SPRT', b'ANIM', b'RAW '))
_PIXELS = {18: ('rgba5551-be', 1, 0), 24: ('ci4', 4, 16), 25: ('ci8', 2, 256)}


def _directory(image, check):
    for anchor in _FIRST.finditer(image):
        base = anchor.start()-24
        if base < 0 or base % 16:
            continue
        check()
        reserved, zero = struct.unpack_from('>II', image, base)
        _, _, first, *_ = _ROW.unpack_from(image, base+8)
        # The first member bounds the on-cartridge rows, before any extra RAM slots.
        count, tail = divmod(first-8, _ROW.size)
        if zero or tail or not 4 <= count <= reserved <= 4096 or base+first > len(image):
            continue
        rows = []
        for name, kind, relative, size, zero, flags, duplicate in _ROW.iter_unpack(image[base+8:base+first]):
            label = name.rstrip(b'\0')
            if (not _NAME.fullmatch(label) or kind not in _KINDS or zero or flags not in (0, 2)
                    or size != duplicate or relative%16 or not first <= relative < relative+size <= len(image)-base):
                break
            rows.append((base+relative, size, flags, kind, label.decode()))
        else:
            rows.sort()
            if all(left[0]+left[1] <= right[0] for left,right in zip(rows,rows[1:])):
                return rows
    return []


def unpack(raw):
    if len(raw) < 9:
        return None
    expected = int.from_bytes(raw[:4], 'big')
    if not 0 < expected <= formats.MAX_BYTES or int.from_bytes(raw[4:7], 'little') != expected or raw[7] != 0x12:
        return None
    try:
        decoder = zlib.decompressobj(wbits=-15)
        data = decoder.decompress(raw[8:], expected+1)
    except zlib.error:
        return None
    return data if len(data) == expected and decoder.eof and not decoder.unused_data else None


def _image(data, kind):
    if len(data) < 24:
        return None
    if kind == b'TXTR':
        offset, palette, words, height, entries, zero = _TEXTURE.unpack_from(data)
        if offset != 16 or palette != offset+2*words*height or entries != 16 or zero or palette+32 != len(data):
            return None
        fmt, factor = 'ci4', 4
    else:
        count, table, ptr, encoding = struct.unpack_from('>4I', data)
        if (count, table, ptr) != (1, 8, 16) or encoding not in _PIXELS:
            return None
        fmt, factor, entries = _PIXELS[encoding]
        palette = 24 if entries else 0
        if entries and struct.unpack_from('>IHH', data, ptr) != (12+2*entries, entries, 1):
            return None
        header = ptr+8+2*entries if entries else ptr
        if header+8 > len(data):
            return None
        size, words, height = struct.unpack_from('>IHH', data, header)
        offset = header+8
        if size != 12+2*words*height or offset+2*words*height != len(data):
            return None
    width = words*factor
    if not 0 < width <= formats.MAX_DIMENSION or not 0 < height <= formats.MAX_DIMENSION:
        return None
    return dict(format=fmt, offset=offset, width=width, height=height, palette_offset=palette)


def _geometry(data):
    if len(data) < 100:
        return None
    h = struct.unpack_from('>25I', data)
    count, groups = h[1:3]
    vertex, batch, index, starts, lengths = h[8], h[10], h[11], h[22], h[23]
    if (h[0] != 0x5d891456 or not 3 <= count <= 32768 or not 0 < groups <= 4096
            or not 100 <= vertex <= vertex+count*_VERTEX.size <= batch < index <= starts < lengths <= len(data)-2*groups
            or index-batch != groups*_BATCH.size or starts+2*groups > lengths):
        return None
    vertices = [entry[:3] for entry in _VERTEX.iter_unpack(data[vertex:vertex+count*_VERTEX.size])]
    groups_start = struct.unpack_from(f'>{groups}H', data, starts)
    groups_size = struct.unpack_from(f'>{groups}H', data, lengths)
    faces = []
    for entry, base, limit in zip(_BATCH.iter_unpack(data[batch:index]), groups_start, groups_size):
        _, elements, first, _, _, _ = entry
        if elements % 3 or index+2*(first+elements) > starts or base+limit > count:
            return None
        lo = index+2*first
        for face in struct.iter_unpack('>3H', data[lo:lo+2*elements]):
            if max(face) >= limit:
                return None
            faces.append(tuple(base+slot for slot in face))
    return (vertices, faces) if faces else None


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for start, size, flags, kind, name in _directory(image, check):
        check()
        if flags != 2 or kind not in (b'MESH', b'TXTR', b'SPRT') or not (data := unpack(image[start:start+size])):
            continue
        common = dict(offset=start, size=size, label=name, confidence='validated',
                      preview_settings=dict(format='auto', source='rom', offset=start))
        if kind == b'MESH':
            if geometry := _geometry(data):
                vertices, faces = geometry
                result.append(dict(common, kind='3d model', media='model', layout=MODEL,
                                   vertices=len(vertices), triangles=len(faces), nodes=1,
                                   meshes=[dict(name=name, vertices=len(vertices), triangles=len(faces))],
                                   reason='The mesh header bounds the vertex array and every triangle index.'))
        elif settings := _image(data, kind):
            result.append(dict(common, kind='image', layout=IMAGE, tag=kind.decode(),
                               width=settings['width'], height=settings['height'],
                               reason='The sprite or texture header declares pixel and palette dimensions.'))
    return result


def preview(image, asset, selection):
    start, size = asset['offset'], asset['size']
    data = unpack(image[start:start+size])
    if data is None:
        raise formats.AssetError('The compressed resource changed. Rescan ROM Explorer.')
    if asset['layout'] == IMAGE:
        if settings := _image(data, asset['tag'].encode()):
            result = formats.preview(data, settings)
            result['settings'] = asset['preview_settings']
            result['details']['note'] = asset['reason']
            return result
    elif geometry := _geometry(data):
        formats.integer(selection.get('mesh', 0), 'Mesh', 0, 0)
        vertices, faces = geometry
        edges = {tuple(sorted((face[i], face[(i+1)%3]))) for face in faces for i in range(3)}
        return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges),
                    points=sorted({i for face in faces for i in face}),
                    surfaces=[dict(indices=face, uv=[[0,0]]*3, colors=[[255]*4]*3, material=0) for face in faces],
                    materials=[], details=dict(format=asset['label'], vertices=len(vertices), triangles=len(faces)),
                    note='Local mesh geometry. Animation and material bindings are separate.',
                    settings=asset['preview_settings'])
    raise formats.AssetError('The resource layout changed. Rescan ROM Explorer.')
