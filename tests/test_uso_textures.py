import struct

import pytest

from decompassets import n64
from decompassets.formats import AssetError
from decompassets.n64 import uso_textures


def _section(kind, data):
    return struct.pack('>3I', kind, len(data), 0) + data


def test_uso_texture_preview_requires_both_relocations():
    pixels = bytes([1]) * (192 * 192)
    palette = bytes(512)
    ci = struct.pack('>4I', 0x110, 0x100, 0, 0)
    raw = pixels + palette + ci
    masks = b'\xff' * ((len(raw)+31)//32*4)
    chunks = 16 + len(masks)
    yay0 = struct.pack('>4s3I', b'Yay0', len(raw), chunks, chunks) + masks + raw
    symbols = b''.join(struct.pack('>3I', 0, off, 0) for off in (0, len(pixels), len(pixels)+512))
    slot = len(raw)-8
    relocations = struct.pack('>6I', 4, slot, 1, 20, slot+4, 1)
    header = struct.pack('>3I20s8x', 0x12345678, 1, 1, b'background.uso') + bytes.fromhex('12345678')
    image = header + _section(6, yay0) + _section(1, symbols) + _section(3, relocations) + _section(11, b'')
    asset, = uso_textures.regions(image)
    assert asset['texture_count'] == 1 and asset['confidence'] == 'tentative'
    preview = n64.preview(image, asset, {})
    assert preview['mime'] == 'image/png' and preview['details']['width'] == 192
    with pytest.raises(AssetError):
        n64.preview(image, asset, {'texture':1})
    broken = image[:-24] + struct.pack('>3I', 20, slot+8, 1) + image[-12:]
    assert not uso_textures.regions(broken)
