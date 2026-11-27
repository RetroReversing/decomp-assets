import struct

from decompassets import n64


def fixture():
    data = bytearray(16+12+128)
    data[16:28] = b'OBJECT_____\0'
    at = 28
    data[at:at+4] = b'G'+(124).to_bytes(3, 'big')
    struct.pack_into('>2H', data, at+12, 3, 3)
    struct.pack_into('>4I', data, at+16, 32, 48, 64, 88)
    for i, point in enumerate(((1,2,3), (4,5,6), (7,8,9))):
        struct.pack_into('>3hH', data, at+4+64+i*8, *point, 0)
    return bytes(data)


def test_position_cloud_and_bad_extent():
    data = fixture()
    assets = [a for a in n64.regions(data) if a.get('layout') == 'embedded-geometry-points']
    assert len(assets) == 1
    preview = n64.preview(data, assets[0], {})
    assert preview['vertices'] == [(1,2,3), (4,5,6), (7,8,9)]
    assert preview['triangles'] == 0 and preview['points'] == [0,1,2]
    assert not any(a.get('layout') == 'embedded-geometry-points' for a in n64.regions(data[:-1]))
