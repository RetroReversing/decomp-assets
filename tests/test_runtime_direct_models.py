import struct

import pytest

from decompassets import formats
from decompassets.n64 import runtime_direct_models as models


def _fixture():
    image = bytearray(4096)
    ram = bytearray(4096)
    vertices = bytearray()
    for i,(x,y,z) in enumerate(((-50,0,0),(50,31,0),(50,-31,31),(50,-31,-31))):
        vertices.extend(struct.pack('>3hH2h4B',x,y,z,0,i*11,i*13,120+i,90+i,60+i,255))
    image[0x500:0x540] = vertices
    ram[0x100:0x140] = vertices
    commands = [(0x04300040,0x80000100),(0xbf000000,0x00000a14),
                (0xbf000000,0x00000a1e),(0xbf000000,0x0000141e),
                (0xb8000000,0)]
    for i,pair in enumerate(commands):
        struct.pack_into('>II',ram,0x200+8*i,*pair)
    return image, ram


def test_captured_nonplanar_mesh_uses_unique_original_vertices():
    image,ram = _fixture()
    assets = models.regions(image,[ram])
    assert len(assets) == 1
    assert (assets[0]['vertices'],assets[0]['triangles']) == (4,3)
    assert models.preview(image,assets[0],{})['triangles'] == 3
    image[0x500] ^= 1
    with pytest.raises(formats.AssetError):
        models.preview(image,assets[0],{})


def test_duplicate_or_changed_vertices_do_not_prove_mapping():
    image,ram = _fixture()
    image[0x600:0x640] = image[0x500:0x540]
    assert not models.regions(image,[ram])
    image,ram = _fixture()
    ram[0x110] ^= 1
    assert not models.regions(image,[ram])


def _segmented_fixture():
    image, ram = _fixture()
    ram[0x200:0x240] = bytes(0x40)
    task = [1, 0, 0x80000080, 0x100, 0x80000088, 0x1000, 0x80000090, 0x100,
            0, 0, 0, 0, 0x80000200, 0, 0, 0]
    struct.pack_into('>16I', ram, 0x20, *task)
    root = [(0xdb060010, 0x80000100), (0xde000000, 0x80000300), (0xdf000000, 0)]
    child = [(0x01004008, 0x04000000), (0x05000204, 0), (0x05000206, 0),
             (0x05000406, 0), (0xdf000000, 0)]
    for base, commands in ((0x200, root), (0x300, child)):
        for i, pair in enumerate(commands):
            struct.pack_into('>II', ram, base+8*i, *pair)
    return image, ram


def test_segmented_task_mesh_uses_the_executed_segment_binding():
    image, ram = _segmented_fixture()
    assets = models.regions(image, [ram])
    assert len(assets) == 1
    assert assets[0]['triangles'] == 3
    assert models.preview(image, assets[0], {})['triangles'] == 3
    # A stale, unexecuted setup cannot establish a binding for the nested list.
    struct.pack_into('>I', ram, 0x200, 0)
    assert not models.regions(image, [ram])


def test_segmented_task_rejects_ambiguous_cartridge_vertices():
    image, ram = _segmented_fixture()
    image[0x600:0x640] = image[0x500:0x540]
    assert not models.regions(image, [ram])
