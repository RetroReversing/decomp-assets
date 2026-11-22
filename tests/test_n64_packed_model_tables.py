import struct

from decompassets.n64 import packed_model_tables as models


def _fixture():
    image = bytearray(0x600)
    words = (0x3c038000, 0x24630200, 0x3c030000, 0x24630400,
             0x3c020000, 0x08000000, 0x24420600)
    struct.pack_into('>7I', image, 0x40, *words)
    vertices = ((1, 2, 3), (-2, 0, 4), (0, 5, -6))
    for index in range(4):
        vertex = index*0x40
        struct.pack_into('>IIHHI', image, 0x200+index*16, vertex+24, vertex, 3, 0, 0)
        for j, (x, y, z) in enumerate(vertices):
            struct.pack_into('>2I', image, 0x400+vertex+j*8,
                             ((x & 0xfff) << 12) | (y & 0xfff), (z & 0xfff) << 20)
        struct.pack_into('>3H', image, 0x400+vertex+24, 0x4002, 0x8012, 0xffff)
    context = dict(segments=[dict(rom_start=0, rom_end=len(image), vram=0x80000000)],
                   functions=[dict(rom_offset=0x40, size=28)])
    return bytes(image), context


def test_packed_model_preview():
    image, context = _fixture()
    assets = models.regions(image, context=context)
    assert len(assets) == 3
    result = models.preview(image, assets[0], {})
    assert result['vertices'] == [(1, 2, 3), (-2, 0, 4), (0, 5, -6)]
    assert result['surfaces'][0]['indices'] == (0, 1, 2)


def test_rejects_unloaded_vertex_and_missing_end():
    image, _ = _fixture()
    broken = bytearray(image)
    struct.pack_into('>H', broken, 0x400+26, 0x8013)
    assert models._mesh(broken, 0x400, (24, 0, 3), 0x440) is None
    broken = bytearray(image)
    struct.pack_into('>H', broken, 0x400+28, 0)
    assert models._mesh(broken, 0x400, (24, 0, 3), 0x41e) is None
