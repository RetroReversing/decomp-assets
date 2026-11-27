import struct

import pytest

from decompassets import formats
from decompassets.n64 import named_prm_models

from .test_named_tim_archives import tim


def model():
    header = bytearray(0x90)
    header[:5] = b'mesh\0'
    struct.pack_into('>H',header,16,4)
    struct.pack_into('>H',header,32,2)
    vertices = b''.join(struct.pack('>hhhH',*point,0) for point in ((0,0,0),(8,0,0),(0,8,0),(8,8,0)))
    triangle = struct.pack('>HH3H',5,1,0,1,2)+bytes(14)
    quad = struct.pack('>HH4H',7,1,0,1,2,3)+bytes(16)
    return bytes(header)+vertices+triangle+quad


def archive():
    files = [(b'one.tim',tim()),(b'two.tim',tim()),(b'mesh.prm',model())]
    table = b''.join(name.ljust(16,b'\0')+struct.pack('<IIB',len(data),len(data),0) for name,data in files)
    return struct.pack('<H',len(files))+table+b''.join(data for _,data in files)


def test_named_model_bounds_vertices_and_faces():
    image = archive()
    asset, = named_prm_models.regions(image)
    shown = named_prm_models.preview(image,asset,{})
    assert shown['details']['vertices'] == 4 and shown['triangles'] == 3
    assert 'triangulation is inferred' in shown['note']


def test_unknown_primitive_bad_index_and_changed_model_are_rejected():
    data = bytearray(model())
    data[0x90+4*8:0x90+4*8+2] = b'\0\x08'
    assert not named_prm_models.mesh(data)
    data = bytearray(model())
    data[0x90+4*8+4:0x90+4*8+6] = b'\0\x04'
    assert not named_prm_models.mesh(data)
    image = archive()
    asset, = named_prm_models.regions(image)
    with pytest.raises(formats.AssetError):
        named_prm_models.preview(image[:-1],asset,{})


@pytest.mark.parametrize('kind,size,indices', [(1,16,3), (2,28,3), (4,32,4), (5,24,3), (7,28,4)])
def test_supported_primitive_kinds_require_bounded_vertex_indices(kind, size, indices):
    data = bytearray(model()[:0x90+4*8])
    struct.pack_into('>H',data,32,1)
    record = struct.pack('>HH',kind,1)+struct.pack('>'+'H'*indices,*range(indices))
    data.extend(record+bytes(size-len(record)))
    result = named_prm_models.mesh(data)
    assert result and len(result[1]) == (2 if indices == 4 else 1)
    struct.pack_into('>H',data,0x90+4*8+4,4)
    assert not named_prm_models.mesh(data)
