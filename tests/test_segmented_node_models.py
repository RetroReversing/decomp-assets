import struct
import zlib

import pytest

from decompassets.formats import AssetError
from decompassets.n64 import segmented_node_models as model


def fixture():
    data=bytearray(0xe8)
    struct.pack_into('>I',data,0,0x05000040)
    struct.pack_into('>6I',data,0x40,0x00180000,0x05000060,0,0,0,0)
    struct.pack_into('>4I',data,0x60,0x050000d0,0,0x050000a0,0x00030000)
    struct.pack_into('>3h',data,0xa0,0,0,0)
    struct.pack_into('>3h',data,0xb0,10,0,0)
    struct.pack_into('>3h',data,0xc0,0,10,0)
    struct.pack_into('>6I',data,0xd0,0x04200030,0x04000000,0xb1000002,0x10,0xb8000000,0)
    return bytes(data)


def packed(data):
    z=zlib.compressobj(wbits=-15)
    return b'\x11\x72'+z.compress(data)+z.flush()


def test_reachable_node_resolves_four_triangle_list():
    raw=fixture();found=model.meshes(raw)
    assert len(found)==1 and found[0]['triangles']==1
    rom=packed(raw);assets=model.regions(rom)
    assert len(assets)==1
    preview=model.preview(rom,assets[0],{'mesh':0})
    assert preview['triangles']==1 and preview['surfaces'][0]['indices']==(0,1,2)


def test_unbounded_vertices_and_invalid_triangles_are_rejected():
    raw=bytearray(fixture());struct.pack_into('>I',raw,0x68,0x0500fff0)
    assert model.meshes(raw)==[]
    raw=bytearray(fixture());struct.pack_into('>I',raw,0xdc,0x80)
    assert model.meshes(raw)==[]
    with pytest.raises(AssetError):model.preview(packed(raw),{'offset':0,'size':len(packed(raw))},{})
