"""Synthetic multi-view models in a size-prefixed asset directory."""

import struct
import zlib

from decompassets.n64 import rare_assets


def fixture():
    model = bytearray(208)
    model[:4] = rare_assets.MODEL
    struct.pack_into('>H', model, 8, 56)
    struct.pack_into('>II', model, 12, 88, 136)
    struct.pack_into('>IH', model, 56, 32, 1)
    struct.pack_into('>IH2xBB', model, 64, 0, 4, 2, 2)
    model[80:88] = b'\xff\xff'*4
    struct.pack_into('>10I', model, 88, 4, 0, 0x06000000, 0x03000000,
                     0x04000c2f, 0x01000000, 0xbf000000, 0x00000204, 0xb8000000, 0)
    struct.pack_into('>H', model, 156, 3)
    for index, (x, y) in enumerate(((0, 0), (1, 0), (0, 1))):
        struct.pack_into('>hh', model, 160+index*16, x, y)
    encoder = zlib.compressobj(wbits=-15)
    packed = b'\x11\x72'+len(model).to_bytes(4,'big')+encoder.compress(model)+encoder.flush()
    table = struct.pack('>II', 17, 0xffffffff)
    table += b''.join(struct.pack('>IHH', index*len(packed), 1, 0) for index in range(17))
    return table+packed*16


def test_directory_member_supports_texture_and_model_views():
    image = fixture()
    model, texture, *_ = rare_assets.regions(image)
    assert model['offset'] == texture['offset']
    assert rare_assets.preview(image, model, {})['triangles'] == 1
    assert rare_assets.preview(image, texture, {})['mime'] == 'image/png'
    assert not rare_assets.regions(image[:-1])



def test_f3dex2_vertex_store_uses_count_in_the_model_header():
    model = bytearray(208)
    model[:4] = rare_assets.MODEL
    struct.pack_into('>II', model, 12, 88, 136)
    struct.pack_into('>H', model, 0x46, 3)
    struct.pack_into('>10I', model, 88, 4, 0, 0xde000000, 0x03000000,
                     0x01003006, 0x01000000, 0x05000204, 0, 0xdf000000, 0)
    for index, (x, y) in enumerate(((0, 0), (1, 0), (0, 1))):
        struct.pack_into('>hh', model, 160+index*16, x, y)
    asset = rare_assets.mesh_region(1,0,len(model),model,modern=True)
    assert asset['layout'] == rare_assets.SEQUEL_MESH
    assert rare_assets.mesh_preview(model,asset,{})['triangles'] == 1
    struct.pack_into('>H', model, 0x46, 2)
    assert rare_assets.mesh_region(1,0,len(model),model,modern=True) is None
