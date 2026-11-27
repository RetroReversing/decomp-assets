"""Paired-directory model lists resolve relative vertices inside their resources."""
import mmap
import struct

import pytest

from decompassets import n64
from decompassets.n64 import paired_rle_images, paired_rle_models


def fixture(*, modern=False):
    raw = bytearray(128)
    for i, (x, y) in enumerate(((0, 0), (10, 0), (0, 10))):
        struct.pack_into('>3h', raw, i*16, x, y, 0)
    commands = ((0x01003006, 0, 0x06000204, 0x00000204, 0xdf000000, 0) if modern
                else (0x04000c2f, 0, 0xb1000204, 0x00000204, 0xb8000000, 0))
    struct.pack_into('>6I', raw, 64, *commands)
    encoded = bytearray()
    for at in range(0, len(raw), 31):
        part = raw[at:at+31]
        encoded.append(0x80+len(part))
        encoded.extend(part)
    block = struct.pack('>I', len(encoded)+4)+encoded+b'\0'
    data = bytearray(0x1000+len(block)+128)
    for at, signature in zip((0x400, 0x500), paired_rle_images._DECODER):
        data[at:at+len(signature)] = signature
    pointers = [0x1000, 0x1000+len(block)] + [0x1000+len(block)+8*i for i in range(1, 16)]
    for index, pointer in enumerate(pointers):
        struct.pack_into('>II', data, 0x100+index*8, pointer, pointer | 0x80000000)
    data[0x1000:0x1000+len(block)] = block
    return bytes(data)


@pytest.mark.parametrize('modern', [False, True])
def test_closed_relative_mesh_is_discovered_and_previewed_in_mapped_rom(tmp_path, modern):
    image = fixture(modern=modern)
    path = tmp_path/'rom.bin'
    path.write_bytes(image)
    with path.open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
        asset, = paired_rle_models.regions(mapped)
        result = n64.preview(mapped, asset, {})
    assert asset['nodes'] == 1 and asset['triangles'] == 2
    assert result['vertices'] == [(0, 0, 0), (10, 0, 0), (0, 10, 0)]
    assert [face['indices'] for face in result['surfaces']] == [(0, 1, 2), (0, 1, 2)]


def test_out_of_bounds_vertex_and_unterminated_lists_are_rejected():
    raw = bytearray(128)
    struct.pack_into('>6I', raw, 64, 0x04000c2f, 0x7fff, 0xb1000204, 0x00000204, 0xb8000000, 0)
    assert not paired_rle_models.meshes(raw)
    struct.pack_into('>I', raw, 68, 0)
    struct.pack_into('>I', raw, 80, 0)
    assert not paired_rle_models.meshes(raw)
