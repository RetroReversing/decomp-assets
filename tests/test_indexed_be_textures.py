import struct
import zlib

import pytest

from decompassets import formats
from decompassets.n64 import indexed_be_textures as textures


def member():
    header = bytearray(32)
    header[2], header[3] = 1, 1
    struct.pack_into('>HHI', header, 6, 8, 2, 0)  # pixel byte count is at offset 12
    struct.pack_into('>I', header, 12, 32)
    pixels = bytes(range(32))
    data = bytearray(header)
    data[3] = 0
    data.extend(pixels)
    compressor = zlib.compressobj(wbits=-15)
    return bytes(header) + len(data).to_bytes(4, 'little') + b'\x09' + compressor.compress(data) + compressor.flush(), pixels


def archive():
    item, pixels = member()
    sections = [0, 2 * len(item), 2 * len(item) + 12] + [2 * len(item) + 12] * 65
    header = bytearray(0x120)
    struct.pack_into('>I68I', header, 0, 67, *sections)
    offsets = struct.pack('>III', 0, len(item), 2 * len(item))
    return bytes(header) + item * 2 + offsets, pixels


def test_archive_texture_preview_unswaps_odd_rows():
    image, pixels = archive()
    assets = textures.regions(image)
    assert len(assets) == 2
    assert (assets[0]['width'], assets[0]['height'], assets[0]['format']) == (8, 2, 'rgba5551-be')
    linear = pixels[:16] + pixels[20:24] + pixels[16:20] + pixels[28:32] + pixels[24:28]
    expected = formats.preview(linear, dict(format='rgba5551-be', width=8, height=2, offset=0))
    assert textures.preview(image, assets[0], {})['data_url'] == expected['data_url']


def test_rejects_truncated_resource_and_bad_header():
    image, _ = archive()
    asset = textures.regions(image)[0]
    with pytest.raises(formats.AssetError):
        textures.preview(image[:-1], dict(asset, size=len(image)), {})
    changed = bytearray(image)
    changed[0x120 + 2] = 7
    assert textures.texture(changed, 0x120, 0x120 + asset['size']) is None


def test_requires_ordered_bounded_section_table():
    image, _ = archive()
    changed = bytearray(image)
    struct.pack_into('>I', changed, 4 + 2 * 4, 0xffffffff)
    assert not list(textures.archives(changed))
