"""Stage meshes encoded as vertex tables and bit-packed display commands."""

import struct
from math import prod

from .. import formats
from . import stage_banks

MODEL = 'mpf-stage-meshes'
_GROUP = struct.Struct('>III')
_SECTION = struct.Struct('>4H')
_CONTROL_WIDTH = (0, 8, 3, 3, 1, 1, 1)


class _Bits:
    def __init__(self, data):
        self.data = data
        self.position = 0

    def read(self, width):
        if self.position + width > len(self.data) * 8:
            raise ValueError('Truncated bit stream')
        index, shift = divmod(self.position, 8)
        self.position += width
        size = (shift + width + 7) // 8
        value = int.from_bytes(self.data[index:index + size], 'little')
        return (value >> shift) & ((1 << width) - 1)

    def signed(self, width):
        value = self.read(width)
        sign = 1 << (width - 1)
        return (value ^ sign) - sign


def _faces(data, slots):
    bits = _Bits(data)
    faces = []
    loaded = cache = 0
    pivot = 1
    while True:
        if bits.read(1):
            width = bits.read(2) + 2
            if width == 5:
                a, b, c = (bits.read(5) for _ in range(3))
            else:
                a, b, c = (pivot + bits.signed(width) for _ in range(3))
            if min(a, b, c) < 0 or max(a, b, c) >= cache:
                raise ValueError('Triangle index outside its vertex batch')
            # Ties follow the original emitter's fallback to the third vertex.
            pivot = a if b < a and c < a else b if a < b and c < b else c
            base = loaded - cache
            faces.append((base + a, base + b, base + c))
            continue
        # Vertex color and UV overrides have no effect on topology.
        for width in (14, 14, 16, 16):
            if bits.read(1):
                bits.read(width)
                break
        else:
            command = bits.read(3)
            if command == 7:
                if loaded != slots:
                    raise ValueError('Display commands did not load the declared vertices')
                return faces
            if command == 0:
                cache = bits.read(5) + 1
                loaded += cache
                if loaded > slots:
                    raise ValueError('Vertex batch exceeds the section')
                pivot = 1
            else:
                bits.read(_CONTROL_WIDTH[command])


def _parts(image, asset, check):
    start, size = asset['offset'], asset['size']
    data = memoryview(image)[start:start + size]
    if len(data) != size or size < 60:
        return
    count, point_start = struct.unpack_from('>2I', data, 24)
    origin = struct.unpack_from('>3i', data, 48)
    point_end = point_start + (count * 33 + 7) // 8
    if not (0 < count <= 4096 and 60 <= point_start < point_end <= size):
        return
    bits = _Bits(data[point_start:point_end])
    points = [tuple(base + bits.signed(11) for base in origin) for _ in range(count)]
    groups = struct.unpack_from('>I', data, 4)[0]
    table_end = 60 + groups * _GROUP.size
    if not (0 < groups <= 256 and table_end <= point_start):
        return
    for index in range(groups):
        check()
        flags, source, _ = _GROUP.unpack_from(data, 60 + index * _GROUP.size)
        if flags or not table_end <= source <= point_start - 0x8c:
            continue
        x, y, z, sections, table = struct.unpack_from('>5I', data, source + 0x50)
        rows = prod((x, y, z))
        stride = 20 + sections * _SECTION.size
        if not (0 < rows <= 256 and 0 < sections <= 256
                and source + 0x8c <= table <= point_start - rows * stride):
            continue
        vertices, faces = [], []
        try:
            for row in range(rows):
                for section in range(sections):
                    pos = table + row * stride + 20 + section * _SECTION.size
                    command_count, slots, commands, records = _SECTION.unpack_from(data, pos)
                    if not command_count:
                        continue
                    commands += source
                    records += source
                    stop = records + (slots * 34 + 7) // 8
                    if not (0 < slots <= 16384 and table + rows * stride <= commands < records
                            and stop <= point_start):
                        raise ValueError('Section outside the stage geometry')
                    triangles = _faces(data[commands:records], slots)
                    bits = _Bits(data[records:stop])
                    base = len(vertices)
                    for _ in range(slots):
                        vertices.append(points[bits.read(12)])
                        bits.read(22)
                    faces.extend(tuple(base + entry for entry in face) for face in triangles)
        except (IndexError, ValueError):
            continue
        if faces:
            yield index, vertices, faces


def regions(image, assets, check):
    for asset in assets:
        if asset['layout'] != stage_banks.TEXTURE:
            continue
        meshes = [dict(group=index, label=f'Stage object {index + 1} · {len(vertices)} vertices',
                       vertices=len(vertices), triangles=len(faces))
                  for index, vertices, faces in _parts(image, asset, check)]
        if meshes:
            yield dict(offset=asset['offset'], size=asset['size'], kind='3d model', media='model',
                       layout=MODEL, confidence='validated', label=f'{len(meshes)} stage meshes',
                       meshes=meshes, nodes=len(meshes),
                       reason='Packed display commands resolve every triangle against its encoded vertex batch.',
                       preview_settings=asset['preview_settings'])


def preview(image, asset, selection):
    index = formats.integer(selection.get('mesh', 0), 'Mesh', 0, len(asset['meshes']) - 1)
    group = asset['meshes'][index]['group']
    for ordinal, vertices, faces in _parts(image, asset, lambda: None):
        if ordinal == group:
            break
    else:
        raise formats.AssetError('The stage mesh changed. Rescan ROM Explorer.')
    edges = {tuple(sorted((face[i - 1], face[i]))) for face in faces for i in range(3)}
    return dict(media='model', vertices=vertices, edges=sorted(edges),
                points=list(range(len(vertices))), triangles=len(faces), materials=[],
                surfaces=[dict(indices=face, uv=[[0, 0]] * 3, colors=[[255] * 4] * 3, material=0) for face in faces],
                details=dict(format='MPF stage geometry', vertices=len(vertices), triangles=len(faces)),
                note='Stage geometry. Preview stage textures separately.',
                settings=dict(asset['preview_settings'], mesh=index))
