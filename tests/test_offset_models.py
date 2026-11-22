import struct
import zlib

import pytest

from decompassets.formats import AssetError
from decompassets.n64 import offset_models as models


def model():
    data = bytearray(0xa0)
    struct.pack_into('>II', data, 4, 0x80, 0x70)
    struct.pack_into('>3H', data, 0x24, 3, 1, 1)
    struct.pack_into('>I', data, 0x38, 0x58)
    struct.pack_into('>hh', data, 0x5a, 0, 0)
    struct.pack_into('>hh', data, 0x66, 3, 1)
    data[0x71:0x74] = bytes((0,1,2))
    for i, point in enumerate(((0,0,0),(10,0,0),(0,10,0))):
        struct.pack_into('>3h', data, 0x80+i*10, *point)
    return bytes(data)


def test_model_geometry_checks_batch_local_indices():
    data = model()
    points, faces = models.geometry(data)
    assert points == [[0,0,0],[10,0,0],[0,10,0]]
    assert faces == [[0,1,2]]
    bad = bytearray(data); bad[0x73] = 3
    assert models.geometry(bad) is None


def test_model_preview_decompresses_and_detects_changed_extent():
    data = model()
    enc = zlib.compressobj(wbits=-15)
    packed = len(data).to_bytes(4,'little') + b'\x09' + enc.compress(data) + enc.flush()
    asset = dict(meshes=[dict(offset=0,size=len(packed),vertices=3,triangles=1)],
                 preview_settings=dict(source='rom',format='auto',offset=0))
    output = models.preview(packed,asset,{})
    assert output['surfaces'][0]['indices'] == [0,1,2]
    asset['meshes'][0]['size'] -= 2
    with pytest.raises(AssetError):
        models.preview(packed,asset,{})


def test_level_segment_uses_its_own_batch_and_vertices():
    data = bytearray(0x110)
    struct.pack_into('>I', data, 4, 0x50)
    struct.pack_into('>H', data, 0x1a, 1)
    struct.pack_into('>II', data, 0x50, 0xe0, 0xd0)
    struct.pack_into('>I', data, 0x5c, 0xb8)
    struct.pack_into('>3H', data, 0x6c, 3, 1, 1)
    struct.pack_into('>hh', data, 0xba, 0, 0)
    struct.pack_into('>hh', data, 0xc6, 3, 1)
    data[0xd1:0xd4] = bytes((0,1,2))
    for i, point in enumerate(((0,0,0),(10,0,0),(0,10,0))):
        struct.pack_into('>3h', data, 0xe0+i*10, *point)
    assert models.geometry(data, 0)[1] == [[0,1,2]]
    assert models.geometry(data, 1) is None
