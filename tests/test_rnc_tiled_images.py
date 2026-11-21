"""The synthetic grid exercises partial-width and partial-height tiles."""

import base64
import struct

from decompassets import n64
from decompassets.n64 import rnc_tiled_images

from .test_rnc import literal_block
from .test_rom_assets import pixels


def test_rnc_tiled_image_preview_stitches_tiles():
    palette = struct.pack('>4H', 0xf801, 0x07c1, 0x003f, 0xffff) + bytes(504)
    tiled = bytes(64*32) + b'\x01'*(8*32) + b'\x02'*(64*2) + b'\x03'*(8*2)
    raw = struct.pack('>IHBB', 0, 0x1801, 0x81, 3) + palette + tiled
    block = literal_block(raw)
    image = bytes(8)+block
    asset, = [a for a in n64.regions(image) if a.get('layout') == rnc_tiled_images.LAYOUT]
    assert (asset['offset'], asset['size'], asset['width'], asset['height']) == (8, len(block), 72, 34)
    result = n64.preview(image, asset, {})
    png = base64.b64decode(result['data_url'].split(',')[1])
    top = b'\xff\0\0\xff'*64 + b'\0\xff\0\xff'*8
    bottom = b'\0\0\xff\xff'*64 + b'\xff'*32
    assert pixels(png) == top*32 + bottom*2
    assert not rnc_tiled_images.regions(image[:-1])
    assert not rnc_tiled_images.regions(literal_block(raw+b'\0'*16))
