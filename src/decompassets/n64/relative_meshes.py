"""Standalone F3DEX and F3DEX2 lists followed by their local vertex arrays."""

import re
import struct

from . import display_lists, display_meshes

_START = re.compile(rb'(?:\x04[\x00-\x3f]|\x01[\x00-\x03])..\x00\x00', re.DOTALL)
_READ = struct.Struct('>II')
_MAX_COMMANDS = 256


def _layout(image, start):
    references = []
    vertex_opcode = image[start]
    terminator = 0xdf000000 if vertex_opcode == 1 else 0xb8000000
    for at in range(start, min(start+_MAX_COMMANDS*8, len(image)-7), 8):
        word, arg = _READ.unpack_from(image, at)
        opcode = word >> 24
        if word == terminator and arg == 0:
            end = at+8
            break
        if opcode == vertex_opcode:
            count = display_lists._vertex_count(word)
            if not count or arg >> 16 or arg % 8:
                return None
            references.append((arg, count))
        elif vertex_opcode == 1:
            if opcode not in (5, 6, 7) or arg >> 24 or opcode == 5 and arg:
                return None
        elif word != 0xbf000000 or arg >> 24:
            return None
    else:
        return None
    cursor = end-start
    for offset, count in references:
        if offset != cursor:
            return None
        cursor += 16*count
    return end if references and start+cursor <= len(image) else None


def regions(image, *, check=lambda: None, progress=lambda _: None):
    assets = []
    for match in _START.finditer(image):
        check()
        start = match.start()
        if start % 8 or not (end := _layout(image, start)):
            continue
        if not (mesh := display_meshes.geometry(image, start, end, {0: start})):
            continue
        _, vertices, faces = mesh
        if len(set(vertices)) < 3:
            continue
        dialect = 'F3DEX2' if image[start] == 1 else 'F3DEX'
        assets.append(dict(offset=start, size=end-start, label=f'{dialect} local mesh', kind='3d model',
                           confidence='validated', media='model', layout='f3dex-mesh',
                           vertices=len(vertices), triangles=len(faces), address_maps=[(0, start)],
                           reason='The closed list loads consecutive vertex arrays immediately after its own commands.',
                           preview_settings=dict(format='auto', source='rom', offset=start)))
        if len(assets) >= display_lists.MAX_TEXTURES:
            break
    return assets
