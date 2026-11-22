import struct

from decompassets.n64 import rnc_quad_models as models


def record():
    result = bytearray(struct.pack('<5I', 0, 16, 4, 48, 1))
    for point in ((0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)):
        result.extend(struct.pack('<3hH', *point, 0))
    result.extend(struct.pack('<6H', 0, 4, 8, 12, 0, 0))
    return result


def test_quad_records_are_bounded_and_triangulated(monkeypatch):
    data = record()+record()
    rows = models.meshes(data)
    assert len(rows) == 2
    assert rows[0][1] == [(0, 1, 2), (0, 2, 3)]
    assert not models.meshes(data[:-1])
    monkeypatch.setattr(models.rnc, 'unpack_at', lambda *_: (data, 12))
    result = models.preview(b'', {'offset': 0, 'reason': '', 'preview_settings': {}}, {'mesh': 1})
    assert result['triangles'] == 2
    data[20+32:20+34] = b'\xff\xff'
    assert not models.meshes(data)
