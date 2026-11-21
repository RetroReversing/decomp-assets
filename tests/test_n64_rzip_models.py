import struct
import zlib

import pytest

from decompassets.formats import AssetError
from decompassets.n64 import rzip_models


def _model():
    vertices = b''.join(struct.pack('>3h10x', *p) for p in ((0, 0, 0), (10, 0, 0), (0, 10, 0)))
    load = (1 << 24) | (3 << 12) | (3 << 1)
    commands = struct.pack('>6I', load, 0x01000000, 0x05000204, 0, 0xdf000000, 0)
    return struct.pack('>10I', 0x28 + len(vertices), len(commands), *([0] * 8)) + vertices + commands


def _packed(data):
    encoder = zlib.compressobj(wbits=-15)
    return struct.pack('>I', len(data)) + encoder.compress(data) + encoder.flush()


def test_model_loads_vertices_and_previews_compressed_geometry():
    data = _model()
    vertices, faces = rzip_models.geometry(data)
    assert vertices == [(0, 0, 0), (10, 0, 0), (0, 10, 0)]
    assert faces == [(0, 1, 2)]
    image = _packed(data)
    model = dict(offset=0, size=len(image), part=0, length=len(data), compressed=True, label='mesh')
    asset = dict(meshes=[model], preview_settings={'format': 'auto'})
    result = rzip_models.preview(image, asset, {})
    assert result['triangles'] == 1
    assert result['surfaces'][0]['indices'] == (0, 1, 2)
    with pytest.raises(AssetError):
        rzip_models.preview(image[:-1], asset, {})


def test_model_rejects_unloaded_triangles_and_bad_list_end():
    data = bytearray(_model())
    at = 0x28 + 3 * 16
    struct.pack_into('>I', data, at + 8, 0x05000206)
    assert rzip_models.geometry(data) is None
    data = bytearray(_model())
    data[-8] = 0
    assert rzip_models.geometry(data) is None


def test_bundle_requires_contiguous_segments_and_final_marker():
    model = _model()
    assert len(model) % 8 == 0
    pieces = (model, bytes(8), bytes(8), bytes(8))
    offset = 32
    header = bytearray()
    for i, piece in enumerate(pieces):
        header += struct.pack('>II', offset, len(piece) | (0x80000000 if i == 3 else 0))
        offset += len(piece)
    bundle = header + b''.join(pieces)
    assert list(rzip_models.segments(bundle))[1][1] == model
    struct.pack_into('>I', bundle, 8, 0)
    assert len(list(rzip_models.segments(bundle))) == 1
