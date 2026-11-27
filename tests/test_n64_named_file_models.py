import struct

from decompassets.n64 import named_file_models


def test_lz_literal_and_truncated_stream():
    data = struct.pack('>IHH', 4, 1, 1) + b'abc' + bytes([ord('d') << 1 & 255, ord('d') >> 7])
    assert named_file_models.unpack(data, 4) == b'abcd'
    assert named_file_models.unpack(data[:-1], 4) is None
    assert named_file_models.unpack(data, 5) is None


def test_mesh_commands_and_bad_indices():
    data = bytearray(100)
    struct.pack_into('>H', data, 0, 0xa492)
    struct.pack_into('>H', data, 2, 2)
    struct.pack_into('>H', data, 6, 3)
    struct.pack_into('>6I', data, 24, 91, 60, 78, 78, 80, 52)
    struct.pack_into('>4H', data, 52, 3, 0, 0, 0)
    struct.pack_into('>9h', data, 60, 0, 0, 0, 1, 0, 0, 0, 1, 0)
    data[80:89] = bytes([0, 0, 0, 1, 0, 0, 2, 0, 0])
    data[91:97] = bytes([0xb0, 2, 0, 0, 0x10, 0x12])
    vertices, faces = named_file_models.mesh(data, 0)
    assert vertices == [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
    assert faces == [(0, 1, 2)]
    data[92] = 1
    assert named_file_models.mesh(data, 0) is None
