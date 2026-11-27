import struct

import pytest

from decompassets.n64 import block16_graphics, runtime_packed_graphics, table_lz_graphics

from .test_runtime_packed_graphics import fixture


def block(data):
    return struct.pack('>II', len(data), len(data)+1) + b'\x80' + data


def test_bounded_tokens_backreferences_rle_and_cancellation():
    # Two literals, one four-byte backreference, then a 16-byte repeated run.
    source = b'\x40\x30\x00AB\x00\x21\x00\x00\x00Z'
    data = struct.pack('>II', 22, len(source)) + source
    assert block16_graphics.inflate(data) == (b'ABABAB' + b'Z'*16, len(data))
    assert block16_graphics.inflate(data[:-1]) is None
    assert block16_graphics.inflate(data[:8] + b'\x40\x80\x00\x00\x21') is None
    with pytest.raises(ValueError, match='stopped'):
        block16_graphics.inflate(data, lambda: (_ for _ in ()).throw(ValueError('stopped')))


def test_three_bounded_blocks_and_runtime_pixels_are_required():
    _, ram = fixture()
    pixels = bytes(ram[0x800:0x900])
    image = bytearray(0x100)
    offsets = []
    for value in (pixels, bytes(range(256)), bytes(reversed(range(256)))):
        image.extend(bytes(-len(image) % 16))
        offsets.append(len(image))
        image.extend(block(value))
        image.extend(bytes(-len(image) % 16))
    spans = block16_graphics.descriptors(image)
    assert len(spans) == 3 and spans[0][0] == offsets[0]
    assets = [a for a in runtime_packed_graphics.regions(image, [ram]) if a.get('codec') == 'block16']
    assert len(assets) == 1 and assets[0]['offset'] == offsets[0]
    assert table_lz_graphics.preview(image, assets[0], {})['mime'] == 'image/png'
    ram[0x880] ^= 1
    assert not [a for a in runtime_packed_graphics.regions(image, [ram]) if a.get('codec') == 'block16']
    image[offsets[1]+8] = 0
    assert not block16_graphics.descriptors(image)
