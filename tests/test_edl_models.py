import struct

from decompassets.n64 import edl, edl_models


def _stream(data):
    out = b'EDL\x80' + struct.pack('>II', len(data) + 12, len(data)) + data
    return out + b'\0' * (-len(out) % 16)


def test_consecutive_polygon_groups_and_preview():
    vertices = b''.join(struct.pack('>3h', i, i * 2, i * 3) for i in range(8))
    face = struct.pack('>I4BH', 3, 0, 1, 2, 3, 0)
    group = struct.pack('>H', 8) + vertices + struct.pack('>H5H', 3, 0, 4, 4, 0, 3) + face * 3
    components = [_stream(group * 3), _stream(bytes(range(32))), _stream(b'abcde')]
    image = b''.join(components)
    offsets = [0, len(components[0]), len(components[0]) + len(components[1])]
    blocks = {offset: edl.header(image, offset)[:3] for offset in offsets}
    assets = edl_models.regions(image, blocks, lambda: None)
    assert len(assets) == 1
    assert assets[0]['nodes'] == 0
    assert len(assets[0]['meshes']) == 3
    result = edl_models.preview(image, assets[0], {'mesh': 1})
    assert result['media'] == 'model'
    assert result['vertices'][1] == (1, 2, 3)
    assert result['triangles'] == 6
    assert result['surfaces'][1]['indices'] == (0, 2, 3)


def test_reject_out_of_range_polygon_and_short_sequences():
    vertices = b'\0' * (8 * 6)
    face = struct.pack('>I4BH', 3, 0, 1, 2, 8, 0)
    group = struct.pack('>H', 8) + vertices + struct.pack('>H5H', 3, 0, 4, 4, 0, 3) + face * 3
    assert edl_models._meshes(group * 3, 32, lambda: None) == []
    assert edl_models._meshes(group[:2], 32, lambda: None) == []
