"""IMG images require a complete palette, bounded pixels and valid LZ references."""
import base64
import struct

from decompassets import n64
from decompassets.n64 import img_textures

from .test_rom_assets import pixels


def image(compressed=False):
    palette = bytes([255, 0, 0, 0, 255, 0])
    header = b'IMG\x1a' + bytes(4) + struct.pack('<HH', 0xc008 if compressed else 0x8008, 2)
    body = header + palette + struct.pack('<HH', 8, 1)
    body += bytes((-len(body)) % 4)
    body += bytes([1, 2, 0xa0, 1, 0x80, 0]) if compressed else bytes([1, 2]*4)
    return body[:4] + struct.pack('<I', len(body)) + body[8:]


def test_uncompressed_and_compressed_palette_preview():
    for compressed in (False, True):
        data = image(compressed)
        asset, = img_textures.regions(data)
        result = n64.preview(data, asset, {})
        rgba = pixels(base64.b64decode(result['data_url'].split(',')[1]))
        assert rgba == bytes([255, 0, 0, 255, 0, 255, 0, 255])*4


def test_reject_invalid_or_truncated_streams():
    data = image(True)
    assert not img_textures.regions(data[:-1])
    assert not img_textures.regions(data[:-4] + bytes([0xa0, 9, 0x80, 0]))
    assert not img_textures.regions(data[:-2] + b'\x80\x01')
    assert not img_textures.regions(data[:8] + b'\x10\xc0' + data[10:])


def test_four_aligned_width_uses_unpadded_stream_rows():
    data = bytearray(image(True))
    data[18:22] = struct.pack('<HH', 4, 2)
    asset, = img_textures.regions(data)
    assert (asset['width'], asset['height']) == (4, 2)
