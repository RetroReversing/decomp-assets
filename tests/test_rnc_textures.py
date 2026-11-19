"""Byte-sum containers and mixed texture records made from synthetic pixels."""

import base64
import struct

import pytest

from decompassets import n64, rnc
from decompassets.n64 import textures

from .test_rnc import literal_block
from .test_rom_assets import pixels


def sum_block(output):
    block = bytearray(literal_block(output))
    struct.pack_into('>I', block, 12, sum(output))
    return block


def mixed_bank():
    first = struct.pack('>B3sBBBBII', 1, b'\xff'*3, 8, 8, 3, 3, 32, 32)
    second = struct.pack('>B3sBBBBII', 0, b'\xff'*3, 8, 8, 3, 3, 288, 320)
    return first + second + b'\xff\0\0\xff'*64 + b'\x00\x3f'*16 + bytes(32)


def test_byte_sum_decoder_and_standard_crc_are_independent():
    raw = mixed_bank()
    block = sum_block(raw)
    assert rnc.unpack_sum32(block) == raw
    with pytest.raises(rnc.RncError, match='packed checksum'):
        rnc.unpack(block)
    with pytest.raises(rnc.RncError, match='sizes'):
        rnc.unpack_sum32(block, max_output=len(raw)-1)
    block[-1] ^= 1
    with pytest.raises(rnc.RncError, match='byte sum'):
        rnc.unpack_sum32(block)


def test_scan_and_preview_both_texture_formats():
    raw = mixed_bank()
    block = sum_block(raw)
    image = bytes(24) + block
    assets = n64.regions(image)
    bank, = [asset for asset in assets if asset.get('layout') == 'rnc-sum32-texture-bank']
    assert bank['offset'] == 24 and bank['size'] == len(block)
    assert len(bank['textures']) == 2
    assert textures.decode(image[24:])[0] == raw
    for index, color in enumerate((b'\xff\0\0\xff', b'\0\0\xff\xff')):
        preview = n64.preview(raw, bank, dict(texture=index))
        assert pixels(base64.b64decode(preview['data_url'].split(',')[1])) == color*64


@pytest.mark.parametrize('field', [8, 20, 28])
def test_scan_rejects_inconsistent_extent_and_dimensions(field):
    raw = bytearray(mixed_bank())
    raw[field + 3] ^= 1
    assert not textures.regions(sum_block(raw))
