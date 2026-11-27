import struct

from decompassets import n64


def fixture(commands=b''):
    data = bytearray(16+12+160)
    data[16:28] = b'OBJECT_____\0'
    at = 28
    data[at:at+4] = b'G'+(156).to_bytes(3, 'big')
    struct.pack_into('>2H', data, at+12, 3, 3)
    struct.pack_into('>4I', data, at+16, 32, 48, 64, 88)
    for i, point in enumerate(((1,2,3), (4,5,6), (7,8,9))):
        struct.pack_into('>3hH', data, at+4+64+i*8, *point, 0)
    data[at+108:at+108+len(commands)] = commands
    return bytes(data)


def test_position_cloud_and_bad_extent():
    data = fixture()
    assets = [a for a in n64.regions(data) if a.get('layout') == 'embedded-geometry-points']
    assert len(assets) == 1
    preview = n64.preview(data, assets[0], {})
    assert preview['vertices'] == [(1,2,3), (4,5,6), (7,8,9)]
    assert preview['triangles'] == 0 and preview['points'] == [0,1,2]
    assert not any(a.get('layout') == 'embedded-geometry-points' for a in n64.regions(data[:-1]))


def test_checked_cache_load_and_triangle_group():
    data = fixture(bytes([0x22, 0, 0, 1, 1, 2, 2, 0xc0, 0, 0x81, 0x08, 0x20]))
    asset = next(a for a in n64.regions(data) if a.get('layout') == 'embedded-geometry-points')
    preview = n64.preview(data, asset, {})
    assert asset['triangles'] == preview['triangles'] == 1
    assert preview['surfaces'][0]['indices'] == (2, 1, 0)
    assert 'Partial' in preview['note']


def test_invalid_triangle_cache_slot_remains_a_vertex_cloud():
    data = fixture(bytes([0x22, 0, 0, 1, 1, 2, 2, 0x81, 0x0c, 0x20]))
    asset = next(a for a in n64.regions(data) if a.get('layout') == 'embedded-geometry-points')
    preview = n64.preview(data, asset, {})
    assert preview['triangles'] == 0
    assert preview['surfaces'] == []
