import base64
import struct
import zlib

from decompassets.n64 import rnc_rgba_tiles as tiles


def fixture():
    data = bytearray(struct.pack('>4H2I', 2, 1, 64, 32, 32, 32))
    data += bytes.fromhex('f801')*1024 + bytes(512)
    data += struct.pack('>II', 32, 32)
    data += bytes.fromhex('07c1')*1024 + bytes(512)
    image = bytes(16) + b'RNC\x01' + struct.pack('>II', len(data), 1) + bytes(7)
    return image, data


def test_grid_tiles_are_assembled_in_order(monkeypatch):
    image, data = fixture()
    monkeypatch.setattr(tiles.rnc, 'unpack', lambda *_args, **_kwargs: data)
    asset = tiles.regions(image)[0]
    result = tiles.preview(image, asset, {})
    png = base64.b64decode(result['data_url'].split(',', 1)[1])
    chunks, at = bytearray(), 8
    while at < len(png):
        length = int.from_bytes(png[at:at+4], 'big')
        if png[at+4:at+8] == b'IDAT':
            chunks.extend(png[at+8:at+8+length])
        at += length+12
    row = zlib.decompress(chunks)
    assert row[1:5] == bytes((255, 0, 0, 255))
    assert row[1+32*4:1+33*4] == bytes((0, 255, 0, 255))
    assert (asset['width'], asset['height']) == (64, 32)


def test_inconsistent_tile_header_and_extent_are_rejected(monkeypatch):
    image, data = fixture()
    monkeypatch.setattr(tiles.rnc, 'unpack', lambda *_args, **_kwargs: data)
    data[16+2560] = 1
    assert tiles.image_at(image, 16) is None
    image, data = fixture()
    data.pop()
    assert tiles.image_at(image, 16) is None
