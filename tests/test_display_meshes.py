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


def test_f3dex2_nonzero_cache_base_single_double_and_quad_commands():
    image = bytearray(128)
    for index in range(4):
        struct.pack_into('>3h', image, 16*index, index%2, index//2, 0)
    # Load slots 4 through 7. F3DEX2 puts the end slot in the low bits.
    struct.pack_into('>12I', image, 64, 0xd9ffffff, 0x220005,
                     0x01004010, 0x0e000000, 0x05080a0c, 0,
                     0x06080a0c, 0x00080c0e, 0x07080a0c, 0x00080c0e, 0xdf000000, 0)
    group = dict(start=64, end=112)
    mappings = {14: 0}
    starts = {14: {64}}
    asset, = display_meshes.regions(image, group, mappings, starts, lambda: None)
    assert asset['label'] == 'F3DEX2 display-list mesh'
    preview = display_meshes.preview(image, asset, {})
    assert [surface['indices'] for surface in preview['surfaces']] == [(0,1,2), (0,1,2), (0,2,3), (0,1,2), (0,2,3)]
    for at, replacement in ((80, 0x05080a10), (84, 0x00000002), (104, 0xb8000000), (80, 0xbf000000)):
        broken = bytearray(image)
        struct.pack_into('>I', broken, at, replacement)
        assert not display_meshes.regions(broken, group, mappings, starts, lambda: None)


def test_f3dex_lighting_and_matrix_pop_allow_a_closed_local_mesh():
    image = bytearray(112)
    for index, (x, y) in enumerate(((0, 0), (1, 0), (0, 1))):
        struct.pack_into('>3h', image, 16 * index, x, y, 0)
    struct.pack_into('>10I', image, 64, 0x03860010, 0x01000030,
                     0x04000c2f, 0x01000000, 0xbf000000, 0x00000204, 0xbd000000, 0, 0xb8000000, 0)
    group = dict(start=72, end=104)
    asset, = display_meshes.regions(image, group, {1: 0}, {1: {64}}, lambda: None)
    assert display_meshes.preview(image, asset, {})['surfaces'][0]['indices'] == (0, 1, 2)
    struct.pack_into('>I', image, 64, 0x03870010)
    assert not display_meshes.regions(image, group, {1: 0}, {1: {64}}, lambda: None)
