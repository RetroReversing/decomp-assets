"""Native material display lists whose texture pointers are offsets into the same file."""

import re
import struct

from . import display_lists

_PROLOGUE = bytes.fromhex('e700000000000000ba00140200000000bb00000180008000')
_END = bytes.fromhex('b800000000000000')
# State setup, synchronization, and texture loads only. Geometry begins in separate files.
_COMMANDS = frozenset((0xba, 0xbb, 0xb6, 0xb7, 0xb9, 0xe6, 0xe7, 0xe8, 0xf0, 0xf2, 0xf3, 0xf4,
                       0xf5, 0xfc, 0xfd))


def material(image, start):
    """Resolve a bounded material program before interpreting its relative addresses."""
    commands = bytearray()
    sources = []
    for at in range(start, min(start+0x400, len(image)-7), 8):
        word, address = struct.unpack_from('>II', image, at)
        if image[at:at+8] == _END:
            end = at + 8 - start
            break
        opcode = word >> 24
        if opcode not in _COMMANDS:
            return []
        if opcode == 0xfd:
            if not 24 <= address < display_lists.MAX_TEXTURE or address % 8:
                return []
            sources.append(address)
            # Feed the usual texture reader a local segmented address.
            address |= 0x01000000
        commands.extend(struct.pack('>II', word, address))
    else:
        return []
    if not sources or min(sources) != end:
        return []
    commands.extend(_END + bytes(8))
    rows = []
    for found in display_lists._textures(commands, dict(start=0, end=end)):
        local = found['address']
        offset, size = start+local, found['bytes']
        if found['swapped'] or not 0 < size <= display_lists.MAX_TEXTURE or offset+size > len(image):
            continue
        if any(local < source < local+size for source in sources):
            continue
        fmt, width, height = found['fmt'], found['width'], found['height']
        settings = dict(format=fmt, width=width, height=height, offset=offset, source='rom')
        palette = []
        entries = []
        if 'palette_address' in found:
            color = start+found['palette_address']
            count = found['palette_entries']
            if not start+end <= color <= offset-2*count:
                continue
            if fmt == 'ci8' and max(image[offset:offset+size]) >= count:
                continue
            settings.update(palette_offset=color, palette_format=found['palette_format'])
            palette.append(color)
            entries.append(count)
        rows.append(dict(offset=offset, size=size, kind='image', confidence='validated',
                         label=f'{display_lists.NAMES[fmt]} {width}×{height} texture',
                         layout='display-list', preview_settings=settings, frames=1, palettes=len(palette),
                         palette_offsets=palette, palette_entries=entries,
                         levels=[dict(width=width, height=height, offset=0)],
                         reason='A closed material display list names texture and palette offsets within its own file.'))
    return rows


def regions(image, *, check=lambda: None, progress=lambda _: None):
    found = {}
    for match in re.finditer(re.escape(_PROLOGUE), image):
        check()
        if match.start() % 8:
            continue
        for asset in material(image, match.start()):
            found.setdefault(asset['offset'], asset)
            if len(found) >= display_lists.MAX_TEXTURES:
                return list(found.values())
    return list(found.values())
