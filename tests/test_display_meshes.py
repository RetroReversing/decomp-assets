import struct

from decompassets.n64 import display_meshes


def test_resolved_f3dex_list_previews_cache_slots_and_rejects_missing_vertices():
    image = bytearray(128)
    for index, (x, y) in enumerate(((0, 0), (1, 0), (0, 1))):
        struct.pack_into('>3h', image, 16*index, x, y, 0)
    struct.pack_into('>6I', image, 64, 0x04000c2f, 0x01000000, 0xbf000000, 0x00000204, 0xb8000000, 0)
    group = dict(start=64, end=88)
    assert not display_meshes.regions(image, group, {1: 0}, {}, lambda: None)
    asset, = display_meshes.regions(image, group, {1: 0}, {1: {64}}, lambda: None)
    preview = display_meshes.preview(image, asset, {})
    assert preview['surfaces'][0]['indices'] == (0, 1, 2)
    assert preview['edges'] == [(0, 1), (0, 2), (1, 2)]
    struct.pack_into('>I', image, 76, 0x00000206)
    assert not display_meshes.regions(image, group, {1: 0}, {1: {64}}, lambda: None)
