"""File-relative F3DEX2 mesh lists in the indexed LZ object directories."""

import struct
from functools import lru_cache

from .. import formats
from . import display_meshes

LAYOUT = 'n64-lz-model-directory'
_MODEL = struct.Struct('>13I')
_COMMAND = struct.Struct('>2I')
# The format stores a high marker bit and a nine-bit per-vertex field.
_VERTEX_FLAGS = 0x81ff
_TEXTURE_COMMANDS = frozenset((0xd7, 0xe6, 0xe7, 0xe8, 0xf0, 0xf2, 0xf3, 0xf5, 0xfd))


def _texture_calls(data, start, end):
    @lru_cache(maxsize=4096)
    def texture_list(offset):
        if not start <= offset < end or offset % 8:
            return False
        loads = False
        for at in range(offset, min(end, offset+512)-7, 8):
            word, value = _COMMAND.unpack_from(data, at)
            opcode = word >> 24
            if opcode == 0xdf:
                return loads and not (word & 0xffffff or value)
            if opcode not in _TEXTURE_COMMANDS or opcode == 0xfd and not 40 <= value < start:
                return False
            loads |= opcode == 0xf3
        return False

    def only_state(word, value):
        return word == 0xde000000 and texture_list(value)

    return only_state


def meshes(data, bank, check):
    model_at, _, palette_at, count, _, palette_count, texture_lists = bank
    end = int.from_bytes(data[4:8], 'big')
    children = _texture_calls(data, texture_lists, model_at)
    minimum = palette_at + palette_count*24
    result = []
    for index in range(count):
        check()
        words = _MODEL.unpack_from(data, model_at + index*_MODEL.size)
        lods = words[0]
        if not 1 <= lods <= 4:
            continue
        for lod, start in enumerate(words[3:13:3][:lods], 1):
            if not minimum <= start < end or start % 8 or data[start] == 0xdf:
                continue
            mesh = display_meshes.geometry(data, start, end, {0: 0}, extra_state=children,
                                            vertex_end=end, vertex_flag_mask=_VERTEX_FLAGS)
            if mesh is None:
                continue
            stop, vertices, faces = mesh
            label = f'Model {index+1}' if lods == 1 else f'Model {index+1}, LOD {lod}'
            result.append(dict(label=label, model_offset=start, model_size=stop-start,
                               vertices=len(vertices), triangles=len(faces)))
    return result


def asset(offset, size, entries):
    return dict(offset=offset, size=size, kind='3d model', media='model', layout=LAYOUT,
                label='Indexed LZ models', confidence='validated', meshes=entries, nodes=len(entries),
                reason='The object directory identifies local F3DEX2 lists with validated vertices, triangles and texture calls.',
                preview_settings=dict(format='auto', source='rom', offset=offset))


def preview(image, asset, selection):
    from . import lz_texture_directories

    offset = asset['offset']
    data, _ = lz_texture_directories.unpack(formats._take(image, offset, asset['size']))
    header = lz_texture_directories.layout(data)
    if header is None:
        raise formats.AssetError('The LZ object directory changed. Rescan ROM Explorer.')
    items = asset['meshes']
    mesh = items[formats.integer(selection.get('mesh', 0), 'Model', 0, len(items)-1)]
    local = dict(offset=mesh['model_offset'], size=mesh['model_size'], address_maps=[(0, 0)],
                 label=mesh['label'], vertex_end=int.from_bytes(data[4:8], 'big'),
                 preview_settings=asset['preview_settings'])
    model_at, *_, texture_lists = header
    return display_meshes.preview(data, local, selection, extra_state=_texture_calls(data, texture_lists, model_at),
                                  vertex_flag_mask=_VERTEX_FLAGS)
