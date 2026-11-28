"""Named texture records use homemade pixels and no game data."""
import base64
import struct

from decompassets.n64 import named_record_textures as textures


def record(name, depth):
    width = height = 8
    pixels = bytes([0xf1])*32 if depth == 4 else bytes.fromhex('f801')*64
    palette = bytes.fromhex('0001f801')+bytes(28) if depth == 4 else b''
    payload = struct.pack('>8H', width, height, depth, 0, 0, 0, 0, 0)+palette+pixels
    return struct.pack('>II', len(payload)+24, 0)+name.ljust(16, b'\0')+payload


def test_adjacent_records_preview_direct_and_paletted_images():
    image = bytes(128)+record(b'first.tex', 4)+record(b'second.tex', 16)
    rows = textures.regions(image)
    assert len(rows) == 2
    for row in rows:
        result = textures.preview(image, row, {})
        assert base64.b64decode(result['data_url'].split(',')[1]).startswith(b'\x89PNG')
    assert not textures.regions(bytes(128)+record(b'first.tex', 4))


def test_named_texture_record_rejects_damaged_boundaries_and_headers():
    first, second = record(b'first.tex', 4), record(b'second.tex', 16)
    image = bytes(128)+first+second
    for at in (128, 132, 142, 128+24, 128+28, 128+len(first)):
        damaged = bytearray(image)
        damaged[at] ^= 1
        assert not textures.regions(damaged)
