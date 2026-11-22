import struct

from decompassets.n64.refpack_opcodes import meshes


def fixture():
    data = bytearray(260)
    data[:8] = b'\0\0\0\x04' + len(data).to_bytes(4, 'big')
    data[64:72] = b'@HEADER\0'
    data[96:106] = b'@VERTICES\0'
    data[128:137] = b'@OPCODES\0'
    node = 152
    struct.pack_into('>II', data, node, 3, 108)
    struct.pack_into('>H', data, node+14, 3)
    for i, point in enumerate(((0, 0, 0), (1, 0, 0), (0, 1, 0))):
        struct.pack_into('>3h', data, node+48+i*16, *point)
    data[248:256] = bytes.fromhex('00 01 10 03 20 12 70 00')
    return data


def test_indexed_triangles_and_invalid_commands():
    data = fixture()
    assert meshes(data)[0][1] == [(0, 1, 2)]
    data[253] = 0x13
    assert meshes(data) == []
    data = fixture()
    data[250] = 0x11
    assert meshes(data) == []
    data = fixture()
    data[252:254] = b'\x60\xff'
    assert meshes(data) == []


def test_mesh_must_fit_declared_container():
    data = fixture()
    data[4:8] = (256).to_bytes(4, 'big')
    assert meshes(data) == []
