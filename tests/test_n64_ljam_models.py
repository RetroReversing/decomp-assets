import struct

from decompassets.n64 import ljam_models


def _array(count, body):
    return b'\x07\x04'+struct.pack('<i', count)+b'\x08\x05'+body+b'\x06'


def _float(value):
    return b'\x03'+struct.pack('<f', value)


def _short(value):
    return b'\x0e'+struct.pack('<H', value)


def _geometry(index=2):
    points = b''.join(_float(v) for v in (0,0,0, 1,0,0, 0,1,0))
    triangles = b'\x0c\x00\x0c\x01\x0c'+bytes([index])
    meta = b'\x27'+_short(0)+b'\x31\x0c\x00'+_short(0)+_short(3)+b'\x2d'+_short(0)+_short(1)
    return (b'\x27'+_array(1,b'\x02mat\0')+b'\x33'+_float(1)
            +b'\x34'+_array(3,points)+b'\x2d'+_array(1,triangles)+b'\x2e'+_array(3,meta))


def test_local_mesh_indices_are_bounded():
    points, faces = ljam_models._mesh(_geometry())
    assert points == [[0,0,0],[1,0,0],[0,1,0]]
    assert faces == [[0,1,2]]
    assert ljam_models._mesh(_geometry(3)) is None
    assert ljam_models._mesh(_geometry()[:-1]) is None


def test_token_array_expansion_and_truncation():
    # An encoded array of three implicit byte tokens.
    assert ljam_models._tokens(b'\x14\x03\x00\x0c\x00\x01\x02') == [(12,0),(12,1),(12,2)]
    assert ljam_models._mesh(b'\x14\xff\xff\x0c') is None
