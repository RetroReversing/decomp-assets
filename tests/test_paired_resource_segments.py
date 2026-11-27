"""Corroborated segment mappings keep external data out of local previews."""
import struct

from decompassets.n64 import paired_resource_models, paired_resource_textures, paired_resources


def _resource():
    data = bytearray(0x1000)
    vertices = b''.join(struct.pack('>3hH2h4B', x,y,0,0,0,0,255,255,255,255)
                        for x,y in ((0,0),(8,0),(0,8)))
    data[0x80:0x80+len(vertices)] = vertices
    for index, at in enumerate((0x100,0x160,0x1c0)):
        struct.pack_into('>I',data,index*24,0x03000000|at)
        struct.pack_into('>8I',data,at,0xe7000000,0,0x01003006,0x03000080,
                         0x05000204,0,0xdf000000,0)
    # Both lists use segment 6 for external data. A naive zero-based segment-6
    # mapping treats the pointer table as 64×64 pixels and its tail as a TLUT.
    decoy = [(0xfd500000,0x06000000),(0xf5500000,0x07000000),(0xe6000000,0),
             (0xf3000000,0x073ff000),(0xe7000000,0),(0xf5400800,0),
             (0xf2000000,0x000fc0fc),(0xfd100000,0x06000800),(0xe8000000,0),
             (0xf5000100,0x07000000),(0xe6000000,0),(0xf0000000,0x0703c000)]
    for i,command in enumerate(decoy):
        struct.pack_into('>2I',data,0x900+i*8,*command)
    return data


def test_local_pointer_table_identifies_geometry_and_rejects_external_texture():
    data = _resource()
    assert paired_resources.local_segments(data) == {3}
    assert not paired_resource_textures.textures(data)
    meshes = paired_resource_models.meshes(data)
    assert len(meshes) == 3 and all(mesh['segment'] == 3 and mesh['triangles'] == 1 for mesh in meshes)


def test_segment_mapping_requires_three_independent_checked_lists():
    data = _resource()
    data[0x1c0] = 0  # the third pointer no longer reaches a display list
    assert not paired_resources.local_segments(data)


def test_texture_can_use_the_independently_proven_local_segment():
    data = _resource()
    data[0x380:0x390] = bytes([0x01])*16
    data[0x3a0:0x3c0] = bytes.fromhex('f80107c1')+bytes(28)
    commands = [(0xfd500000,0x03000380),(0xf5500000,0x07000000),(0xe6000000,0),
                (0xf3000000,0x07007000),(0xe7000000,0),(0xf5400200,0),
                (0xf2000000,0x0003c004),(0xfd100000,0x030003a0),(0xe8000000,0),
                (0xf5000100,0x07000000),(0xe6000000,0),(0xf0000000,0x0703c000)]
    for i,command in enumerate(commands):
        struct.pack_into('>2I',data,0x480+i*8,*command)
    texture, = paired_resource_textures.textures(data)
    assert texture['preview_settings']['offset'] == 0x380
    assert texture['preview_settings']['palette_offset'] == 0x3a0
