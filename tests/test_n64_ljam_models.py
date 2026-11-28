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


def test_multiple_groups_rebase_local_indices_without_overlap():
    points = b''.join(_float(v) for v in (0,0,0, 1,0,0, 0,1,0, 2,0,0, 3,0,0, 2,1,0))
    face = b'\x0c\x00\x0c\x01\x0c\x02'
    def group(vertex, triangle):
        return b'\x27'+_short(0)+b'\x31\x0c\x00'+_short(vertex)+_short(3)+b'\x2d'+_short(triangle)+_short(1)
    def geometry(second):
        return (b'\x27'+_array(1,b'\x02mat\0')+b'\x34'+_array(6,points)
                +b'\x2d'+_array(2,face*2)+b'\x2e'+_array(6,group(0,0)+group(3,second)))
    assert ljam_models._mesh(geometry(1))[1] == [[0,1,2],[3,4,5]]
    assert ljam_models._mesh(geometry(0)) is None


def test_groups_reuse_only_initialized_vertex_cache_slots():
    points = b''.join(_float(v) for v in (0,0,0, 1,0,0, 0,1,0, 2,0,0, 3,0,0))
    face = b'\x0c\x00\x0c\x01\x0c\x02'
    def group(slot, offset, count, triangle):
        return (b'\x27'+_short(0)+b'\x31\x0c'+bytes([slot])+_short(offset)+_short(count)
                +b'\x2d'+_short(triangle)+_short(1))
    def geometry(first_count):
        return (b'\x27'+_array(1,b'\x02mat\0')+b'\x34'+_array(5,points)+b'\x2d'+_array(2,face*2)
                +b'\x2e'+_array(6,group(0,0,first_count,0)+group(1,3,2,1)))
    assert ljam_models._mesh(geometry(3))[1] == [[0,1,2],[0,3,4]]
    assert ljam_models._mesh(geometry(2)) is None
