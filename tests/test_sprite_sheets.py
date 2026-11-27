"""Sprite previews require a complete palette and consistent frame directory."""
import base64
import struct

from decompassets import n64
from decompassets.n64 import sprite_sheets

from .test_rom_assets import pixels


def sheet():
    data = b'SPR\x1a' + bytes(4) + struct.pack('<HH', 0x8008, 2)
    data += bytes([255, 0, 0, 0, 255, 0])
    data += bytes((-len(data)) % 4)
    data += bytes(6) + struct.pack('<HHH', 2, 1, 2)
    data += struct.pack('<IHHHH', 0, 0, 0, 2, 1) + struct.pack('<IHHHH', 2, 0, 0, 2, 1)
    data += bytes([1, 2, 2, 1])
    return data[:4] + struct.pack('<I', len(data)) + data[8:]


def test_frame_directory_preview():
    data = sheet()
    asset, = sprite_sheets.regions(data)
    assert asset['frame_count'] == 2
    result = n64.preview(data, asset, {})
    assert pixels(base64.b64decode(result['data_url'].split(',')[1])) == bytes([
        255, 0, 0, 255, 0, 255, 0, 255, 0, 255, 0, 255, 255, 0, 0, 255,
    ])


def test_reject_bad_frame_or_truncated_pixels():
    data = sheet()
    assert not sprite_sheets.regions(data[:-1])
    bad = bytearray(data)
    bad[-16] = 3  # Second frame's offset must follow the first frame.
    assert not sprite_sheets.regions(bad)
    assert not sprite_sheets.regions(data[:-1] + b'\x03')
