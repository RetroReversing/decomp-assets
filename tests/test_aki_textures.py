"""Inline indexed texture headers must contain a complete palette and image."""
import base64
import struct

from decompassets import n64
from decompassets.n64 import aki_textures

from .test_rom_assets import pixels


def image(bits=4):
    colours = 1 << bits
    palette = bytes.fromhex('f80107c1') + bytes((colours-2)*2)
    bitmap = bytes.fromhex('0110') if bits == 4 else bytes([0, 1, 1, 0])
    return b'TEX\0' + struct.pack('>HHBBH', 2, 2, bits, 2, colours) + bytes(4) + palette + bitmap


def test_indexed_textures_show_the_inline_palette():
    for bits in (4, 8):
        data = image(bits)
        asset, = aki_textures.regions(data)
        result = n64.preview(data, asset, {})
        rgba = pixels(base64.b64decode(result['data_url'].split(',')[1]))
        assert rgba[:8] == bytes([255, 0, 0, 255, 0, 255, 0, 255])


def test_reject_truncated_or_invalid_header():
    data = image()
    assert not aki_textures.regions(data[:-1])
    assert not aki_textures.regions(data[:9] + b'\x04' + data[10:])
    assert not aki_textures.regions(data[:12] + b'\x01' + data[13:])
