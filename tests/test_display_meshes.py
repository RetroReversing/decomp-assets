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


def test_fast3d_loads_and_triangles_use_ten_byte_cache_indices():
    image = bytearray(128)
    for index, (x, y) in enumerate(((0, 0), (1, 0), (0, 1))):
        struct.pack_into('>3h', image, 16*index, x, y, 0)
    # Load three vertices into cache slots 4–6, then address them in units of ten.
    struct.pack_into('>6I', image, 64, 0x04240030, 0x01000000,
                     0xbf000000, 0x0028323c, 0xb8000000, 0)
    group = dict(start=64, end=88)
    asset, = display_meshes.regions(image, group, {1: 0}, {1: {64}}, lambda: None)
    assert asset['label'] == 'Fast3D display-list mesh'
    assert display_meshes.preview(image, asset, {})['surfaces'][0]['indices'] == (0, 1, 2)
    struct.pack_into('>I', image, 76, 0x0028323d)
    assert not display_meshes.regions(image, group, {1: 0}, {1: {64}}, lambda: None)
    struct.pack_into('>I', image, 76, 0x00283246)
    assert not display_meshes.regions(image, group, {1: 0}, {1: {64}}, lambda: None)


def test_preview_binds_the_texture_at_each_draw_and_preserves_uvs():
    import base64

    from .test_display_list_textures import build
    from .test_rom_assets import pixels

    image, texture, palette = build()
    image = bytearray(image)
    start = 0x200c0
    # Replace an RDP synchronization with G_TEXTURE and make both triangles address
    # the three loaded slots. Give the first vertex one full texture-width in S.
    struct.pack_into('>II', image, start + 10*8, 0xbb000001, 0xffff8000)
    for command in (14, 16):
        struct.pack_into('>I', image, start + command*8 + 4, 0x00000204)
    struct.pack_into('>2h', image, 0x20020 + 8, 8*32, 4*32)
    asset = dict(offset=start, size=18*8, label='F3DEX display-list mesh',
                 address_maps=[[0x80, -0xe0000]], preview_settings={'format': 'auto'})
    preview = display_meshes.preview(image, asset, {})
    assert len(preview['surfaces']) == 2
    assert preview['surfaces'][0]['material'] == 1
    assert preview['materials'][1]['offset'] == texture
    assert pixels(base64.b64decode(preview['materials'][1]['image'].split(',')[1]))[:8] == bytes(
        [255, 0, 0, 255, 0, 255, 0, 255])
    assert preview['surfaces'][0]['uv'][0] == [65535/65536, 0.25]
    # A later draw may disable texturing without changing earlier surfaces.
    struct.pack_into('>II', image, start + 15*8, 0xbb000000, 0)
    changed = display_meshes.preview(image, asset, {})
    assert [face['material'] for face in changed['surfaces']] == [1, 0]
    struct.pack_into('>II', image, start + 15*8, 0x04000c2f, 0x80100050)
    # Shifted or different S/T wrapping cannot be represented by this renderer.
    struct.pack_into('>I', image, start + 11*8 + 4, 1)
    assert all(x['material'] == 0 for x in display_meshes.preview(image, asset, {})['surfaces'])
    struct.pack_into('>I', image, start + 11*8 + 4, 0x100)
    assert all(x['material'] == 0 for x in display_meshes.preview(image, asset, {})['surfaces'])
    struct.pack_into('>I', image, start + 11*8 + 4, 0)
    # Texture state disabled, or palette outside the image, must never guess a link.
    struct.pack_into('>I', image, start + 10*8, 0xbb000000)
    assert all(x['material'] == 0 for x in display_meshes.preview(image, asset, {})['surfaces'])
    struct.pack_into('>I', image, start + 10*8, 0xbb000001)
    struct.pack_into('>I', image, start + 4, 0x80ffffff)
    assert all(x['material'] == 0 for x in display_meshes.preview(image, asset, {})['surfaces'])
