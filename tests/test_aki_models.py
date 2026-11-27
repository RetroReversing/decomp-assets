"""Only a corroborated directory and complete indexed geometry make a mesh."""
import struct

from decompassets import n64
from decompassets.n64 import aki_models

from .test_aki_textures import image as texture


def literal(data):
    out = bytearray(len(data).to_bytes(4, 'big'))
    for at in range(0, len(data), 8):
        out.append(255)
        out.extend(data[at:at+8])
    return bytes(out)


def mesh():
    vertices = [(0, 0, 0), (10, 0, 0), (0, 10, 0)]
    return bytes([1, 3, 2, 0, 0, 0, 0, 0]) + b''.join(
        struct.pack('bbb', *v) + bytes(5) for v in vertices) + bytes([0, 1, 2, 0, 2, 1])


def cartridge():
    files = [texture(), texture(), texture(), mesh(), literal(mesh())] + [b'\0\0']*252
    data = bytearray()
    offsets = []
    for i, entry in enumerate(files):
        if len(data) % 2:data.append(0)
        offsets.append(len(data) | (i == 4))
        data.extend(entry)
    if len(data) % 2:data.append(0)
    offsets.append(len(data))
    data.extend(b''.join(struct.pack('>I', x) for x in offsets))
    return bytes(data)


def test_checked_directory_exposes_raw_and_compressed_meshes():
    data = cartridge()
    found = aki_models.regions(data)
    assert len(found) == 2
    for asset in found:
        result = n64.preview(data, asset, {})
        assert result['vertices'] == [(0, 0, 0), (10, 0, 0), (0, 10, 0)]
        assert result['triangles'] == 2


def test_reject_invalid_mesh_stream_and_directory():
    data = cartridge()
    assert aki_models._mesh(mesh()[:-1]) is None
    assert aki_models._mesh(mesh()[:-1] + b'\x09') is None
    assert aki_models._decode(literal(mesh())[:-1]) is None
    assert not aki_models.regions(data.replace(b'TEX\0', b'NOPE'))
