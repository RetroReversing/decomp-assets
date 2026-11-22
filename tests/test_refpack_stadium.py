import struct

from decompassets.n64.refpack_stadium import meshes


def fixture():
    data = bytearray(264)
    data[:8] = b'\0\0\0\x05' + len(data).to_bytes(4, 'big')
    data[64:72] = b'@HEADER\0'
    data[96:106] = b'@VERTICES\0'
    data[128:136] = b'@MESHES\0'
    node = 152
    struct.pack_into('>II', data, node, 3, 112)
    struct.pack_into('>H', data, node+14, 3)
    for i, point in enumerate(((0, 0, 0), (1, 0, 0), (0, 1, 0))):
        struct.pack_into('>3h', data, node+48+i*16, *point)
    struct.pack_into('>5H', data, 248, 0x00b5, 0xffff, 0, 0, 1)
    return data


def test_bounded_triangle_batches():
    data = fixture()
    rows = meshes(data)
    assert len(rows) == 1
    assert rows[0][1] == [(0, 1, 2)]
    data[248] = 1
    assert meshes(data) == []
