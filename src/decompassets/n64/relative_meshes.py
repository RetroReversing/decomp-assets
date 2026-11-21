"""Standalone F3DEX lists immediately followed by their local vertex arrays."""

import re
import struct

from . import display_lists, display_meshes

_START = re.compile(rb'\x04[\x00-\x3f]..\x00\x00', re.DOTALL)
_READ = struct.Struct('>II')
_MAX_COMMANDS = 128


def _layout(image, start):
    references = []
    for at in range(start, min(start+_MAX_COMMANDS*8, len(image)-7), 8):
        word, arg = _READ.unpack_from(image, at)
        opcode = word >> 24
        if word == 0xb8000000 and arg == 0:
            end = at+8
            break
        if opcode == 4:
            # F3DEX's packed byte count and destination slot disambiguate it from Fast3D.
            count = display_lists._vertex_count(word)
            if not count or arg >> 16 or arg % 8:
                return None
            references.append((arg, count))
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
        assets.append(dict(offset=start, size=end-start, label='F3DEX local mesh', kind='3d model',
                           confidence='validated', media='model', layout='f3dex-mesh',
                           vertices=len(vertices), triangles=len(faces), address_maps=[(0, start)],
                           reason='The closed list loads consecutive vertex arrays immediately after its own commands.',
                           preview_settings=dict(format='auto', source='rom', offset=start)))
        if len(assets) >= display_lists.MAX_TEXTURES:
            break
    return assets
