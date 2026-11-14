"""Display-list textures, exercised only with a homemade cartridge: one file pre-linked to a RAM address."""
import base64
import struct

import pytest

from decompassets import n64
from decompassets.n64 import display_lists, textures

from .test_rom_assets import pixels

BASE = 0x80100000
RED, GREEN = bytes.fromhex('f801'), bytes.fromhex('07c1')


def cmd(w0, w1=0):return struct.pack('>II', w0, w1)


def vertex(x):return struct.pack('>hhhhhhBBBB', x, 2, 3, 0, 0, 0, 255, 255, 255, 255)


def build(*, tlut_first=True, pointer=True, segment=None, palette_entries=16):
    """A file: a pointer to its list, two vertex arrays, a palette, an 8x8 CI4 texture, then the list."""
    space = (segment << 24) if segment else BASE
    table, vertices = 0x10, 0x20
    palette = vertices + 6*16
    texture = palette + 2*palette_entries
    dl = texture + 32
    def address(offset):return space + offset
    tlut = [cmd(0xFD100000, address(palette)), cmd(0xE8000000), cmd(0xF5000100, 0x07000000), cmd(0xE6000000),
            cmd(0xF0000000, (7 << 24) | ((palette_entries-1) << 14)), cmd(0xE7000000)]
    load = [cmd(0xFD500000, address(texture)), cmd(0xF5500000, 0x07000000), cmd(0xE6000000),
            cmd(0xF3000000, (7 << 24) | (15 << 12) | 0x800), cmd(0xE7000000),
            cmd(0xF5000000 | (2 << 21) | (1 << 9), 0), cmd(0xF2000000, (28 << 12) | 28)]
    draw = [cmd(0x04000000 | (3 << 10) | 47, address(vertices)), cmd(0xBF000000, 0x00020406),
            cmd(0x04000000 | (3 << 10) | 47, address(vertices + 48)), cmd(0xBF000000, 0x00020406), cmd(0xB8000000)]
    # Loaded the other way round, an earlier palette is still in TMEM when the tile's size is set.
    decoy = [cmd(0xFD100000, address(table)), cmd(0xF5000100, 0x07000000), cmd(0xF0000000, (7 << 24) | (15 << 14))]
    body = (decoy + load + tlut + draw) if not tlut_first else (tlut + load + draw)
    file = bytearray(dl + 8*len(body))
    if pointer:file[table:table+4] = address(dl).to_bytes(4, 'big')
    file[vertices:vertices+96] = b''.join(vertex(10+i) for i in range(6))
    file[palette:palette+2*palette_entries] = (RED + GREEN + RED*14 + GREEN*(palette_entries-16))[:2*palette_entries]
    file[texture:texture+32] = bytes([0x01, 0x10]*16)       # red, green, green, red ...
    file[dl:] = b''.join(body)
    image = bytearray(0x40000)
    image[0x20000:0x20000+len(file)] = file
    return bytes(image), 0x20000 + texture, 0x20000 + palette


@pytest.mark.parametrize('options', [{}, dict(tlut_first=False), dict(segment=6)])
def test_texture_is_placed_by_its_files_vertices_and_list_pointer(options):
    image, texture, palette = build(**options)
    found = display_lists.regions(image)
    assert [(a['offset'], a['preview_settings']['format'], a['preview_settings']['width'], a['palette_offsets'])
            for a in found] == [(texture, 'ci4', 8, [palette])]
    asset = found[0]
    assert asset['label'] == 'CI4 8×8 texture' and asset['confidence'] == 'inferred' and asset['palette_entries'] == [16]
    shown = pixels(base64.b64decode(textures.preview(image, asset, {})['data_url'].split(',')[1]))
    assert shown[:8] == bytes([255, 0, 0, 255, 0, 255, 0, 255])
    # The N64 recogniser list includes it, and its preview path reads it the same way.
    whole = [a for a in n64.regions(image) if a.get('layout') == 'display-list']
    assert n64.preview(image, whole[0], {})['data_url'] == textures.preview(image, asset, {})['data_url']


def test_without_a_pointer_to_the_list_nothing_is_guessed():
    image, _, _ = build(pointer=False)
    assert display_lists.regions(image) == []


def test_a_palette_load_after_the_tile_size_is_the_one_drawn_with():
    """A palette loaded after the tile size replaces the one in TMEM before the texture is drawn."""
    image, texture, palette = build(tlut_first=False)
    assert display_lists.regions(image)[0]['palette_offsets'] == [palette]


def test_a_list_placed_outside_ram_is_rejected():
    image, _, _ = build()
    assert display_lists._ram_bounds(0x80, [0x20000, 0x30000]) == (0x30000 - display_lists.RDRAM + 1, 0x20000)
    assert display_lists._ram_bounds(6, [0x20000])[0] < 0


def test_vertex_load_words_of_each_microcode():
    assert display_lists._vertex_count(0x04000000 | (8 << 10) | 127) == 8           # F3DEX
    assert display_lists._vertex_count(0x04000000 | (7 << 20) | 128) == 8           # Fast3D
    assert display_lists._vertex_count(0x01000000 | (8 << 12) | (8 << 1)) == 8      # F3DEX2
    assert display_lists._vertex_count(0x04000000 | (8 << 10) | 126) == 0


def test_scan_stops_and_cartridges_without_lists_are_quick():
    image, _, _ = build()
    def stop():raise RuntimeError('stopped')
    with pytest.raises(RuntimeError, match='stopped'):display_lists.regions(image, check=stop)
    assert display_lists.regions(bytes(0x10000)) == []
