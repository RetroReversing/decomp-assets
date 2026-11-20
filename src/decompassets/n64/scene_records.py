"""Inspect bounded level sectors, path keyframes and cutscene command records."""

import math
import struct

from ..formats import AssetError
from .resource_inspection import table

KEYFRAME = struct.Struct('>H15f')
# The script interpreter advances by the fixed width of each opcode. Keep
# operands opaque until the corresponding handlers establish their meanings.
COMMAND_WIDTHS = (
    0, 32, 264, 4, 20, 272, 20, 32, 8, 32, 8, 8, 20, 8, 4, 8, 8, 8, 8, 16, 8, 12, 20, 12, 24, 24,
    8, 4, 8, 8, 44, 8, 16, 16, 20, 20, 12, 16, 8, 4, 8, 4, 12, 8, 8, 8, 4, 24, 24, 24, 24, 8,
)


def _path(data):
    count, field = struct.unpack_from('>HH', data, 4)
    if not 1 <= count <= 1058 or len(data) != 8 + count * (2 + KEYFRAME.size):
        return None
    start = 8 + count * 2
    offsets = (word for word, in struct.iter_unpack('>H', data[8:start]))
    if any(offset != index * KEYFRAME.size for index, offset in enumerate(offsets)):
        return None
    rows = []
    for tick, x, y, z, *_ in KEYFRAME.iter_unpack(data[start:]):
        if not all(math.isfinite(v) for v in (x, y, z)):
            return None
        rows.append(dict(tick=tick, x=round(x, 4), y=round(y, 4), z=round(z, 4)))
    return 'PATH keyframes', 'animation', {'Keyframes': count, 'Header value': field}, rows


def _cutscene(data):
    mode, auxiliary_offset, count = struct.unpack_from('>iII', data, 4)
    if not 0 < count <= 4096 or auxiliary_offset > len(data) - 16:
        return None
    at = 16
    rows = []
    for _ in range(count):
        if at + 4 > len(data):
            return None
        opcode, = struct.unpack_from('>I', data, at)
        width = COMMAND_WIDTHS[opcode] if opcode < len(COMMAND_WIDTHS) else 0
        if not width or at + width > len(data):
            return None
        operands = [f'{word:08X}' for word, in struct.iter_unpack('>I', data[at + 4:at + width])]
        rows.append(dict(decoded_offset=at, opcode=opcode, size=width, operand_words=operands))
        at += width
    if at != len(data):
        return None
    return 'NCS cutscene commands', 'container', {'Commands': count, 'Header mode': mode,
                                                   'Auxiliary offset': auxiliary_offset}, rows


def _level(data):
    if len(data) < 92 or data[:20] != b'ELv9\0\0\0\1\0\0\0\0ES_1NONE':
        return None
    extent, = struct.unpack_from('>I', data, 20)
    slots, = struct.unpack_from('>I', data, 88)
    if extent != len(data) - 20 or not 0 < slots <= 1024:
        return None
    at = 92
    seen = set()
    rows = []
    while at + 12 <= len(data) and data[at:at + 4] == b'SCTR':
        sector, extent = struct.unpack_from('>II', data, at + 4)
        end = at + 8 + extent
        if sector >= slots or sector in seen or not 4 <= extent <= len(data) - at - 8:
            return None
        seen.add(sector)
        rows.append(dict(sector=sector, decoded_offset=at, size=end - at))
        at = end
    if not rows or data[at:at + 4] != b'ANTX':
        return None
    return 'ELv9 level sectors', 'container', {'Sector slots': slots, 'Stored sectors': len(rows),
                                               'Trailing ANTX offset': at}, rows


def layout(data):
    if len(data) < 16:
        return None
    reader = {b'PATH': _path, b'NCS\0': _cutscene, b'ELv9': _level}.get(bytes(data[:4]))
    return reader(data) if reader else None


def asset(data, offset, extent):
    found = layout(data)
    if found is None:
        return None
    label, kind, fields, _ = found
    return dict(offset=offset, size=extent, kind=kind, confidence='validated', media='metadata',
                layout='scene-records', resource_type='scene records', label=label, resource_fields=fields,
                reason='The byte sum, record extents and record references agree.',
                preview_settings=dict(format='auto', source='decoded', offset=0, block_offset=offset))


def preview(data, asset, selection):
    found = layout(data)
    if found is None:
        raise AssetError('The scene record changed. Rescan ROM Explorer.')
    title, _, fields, rows = found
    records = table(title, ['index', *rows[0]], len(rows), rows.__getitem__, selection)
    result = dict(media='metadata', title=title, fields=fields, table=records,
                  settings=dict(format='auto', source='rom', offset=asset['offset']))
    if data.startswith(b'PATH'):
        vertices = [[row['x'], row['y'], row['z']] for row in rows]
        result['geometry'] = dict(vertices=vertices, edges=[(i, i + 1) for i in range(len(vertices) - 1)],
                                  points=list(range(len(vertices))), triangles=0,
                                  note='Stored keyframe positions in order.')
    return result
