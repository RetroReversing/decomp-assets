"""Chunked RNC streams with an FFS filesystem, and a deflated asset table with models: homemade data only."""
import base64
import struct
import zlib

import pytest

from decompassets import n64, rnc
from decompassets.n64 import ffs, rare_models

from .test_rnc import literal_block
from .test_rom_assets import pixels

RED, GREEN = bytes.fromhex('f801'), bytes.fromhex('07c1')


def chunked(output):
    """A method-0x81 stream: each 4 KB chunk a literal-only method-1 stream, padded to an even length."""
    payloads = [literal_block(output[at:at+4096])[rnc.HEADER_BYTES:] for at in range(0, len(output), 4096)]
    body = b''.join(p + bytes(len(p) & 1) for p in payloads)
    table = b''.join(struct.pack('>H', len(p)) for p in payloads)
    return b'RNC\x81' + struct.pack('>IIHHBB', len(output), len(table) + len(body), 0, 0, 0, 0) + table + body


def i64(code, width, height, palette=b'', pixels_=b''):
    return b'I64\0' + struct.pack('>3I', width, height, code) + palette + pixels_


def filesystem(files):
    table = 12 + 24*len(files)
    records, data, at = b'', b'', table
    for index, body in enumerate(files):
        records += struct.pack('>3I', 0x100 + index, len(body), at) + bytes(12)
        data += body;at += len(body)
    return b'FFS\0' + struct.pack('>II', len(files), 0) + records + data


def test_chunked_stream_reads_any_range_from_its_own_chunks():
    output = bytes(range(256)) * 40
    image = bytes(10) + chunked(output)
    layout = rnc.chunked(image, 10)
    assert layout['size'] == len(output) and len(layout['chunks']) == 3
    assert rnc.unpack_chunked(image, layout, 4000, 8300) == output[4000:8300]
    assert rnc.unpack_chunked(image, layout) == output
    with pytest.raises(rnc.RncError):rnc.unpack_chunked(image, layout, 0, len(output) + 1)
    assert rnc.chunked(image[:-1], 10) is None and rnc.chunked(image, 11) is None


def test_ffs_images_are_found_grouped_by_chunk_and_previewed():
    ci4 = i64(0, 8, 2, RED + GREEN + RED*14, bytes([0x01]*8))
    grey = i64(5, 4, 4, b'', bytes([255]*16))
    wrong = i64(0, 8, 2, RED*16, bytes(7))                           # one pixel byte short
    stream = filesystem([ci4, b'not an image', grey, wrong, bytes(5000), ci4])
    image = bytes(64) + chunked(stream)
    found = ffs.regions(image)
    assert [len(a['textures']) for a in found] == [2, 1]             # two images start in chunk 0, one in chunk 1
    assert [t['preview_settings']['format'] for a in found for t in a['textures']] == ['ci4', 'i8', 'ci4']
    assert found[0]['offset'] == rnc.chunked(image, 64)['chunks'][0][0]
    shown = pixels(base64.b64decode(ffs.preview(image, found[0], {'texture': 0})['data_url'].split(',')[1]))
    assert shown[:8] == bytes([255, 0, 0, 255, 0, 255, 0, 255])
    assert n64.preview(image, found[0], {'texture': 1})['details']['format'] == 'i8'
    assert any(a.get('layout') == 'ffs-i64' for a in n64.regions(image))


def deflated(body, header=b'\x00\x82'):
    stream = zlib.compressobj(9, zlib.DEFLATED, -15)
    return header + stream.compress(body) + stream.flush()


def model(textures, first_offset=0):
    """A model: magic, the texture list's offset at 8, then the list (size, count, entries) and the data."""
    setup = 0x50
    entries, data, at = b'', b'', first_offset
    for kind, width, height, body in textures:
        entries += struct.pack('>IHBB', at, kind, width, height);data += body;at += len(body)
    data = bytes(first_offset) + data
    head = bytearray(setup);head[:4] = b'\0\0\0\x0b';head[8:10] = setup.to_bytes(2, 'big')
    return bytes(head) + struct.pack('>IHH', 8 + len(entries) + len(data), len(textures), 0) + entries + data


def asset_table(assets):
    blobs = [deflated(a) for a in assets]
    blobs = [b + bytes(-len(b) % 4) for b in blobs]
    entries, at = [], 0
    for blob in blobs + [b'']:
        entries.append((at//4) << 8 | 0x13);at += len(blob)
    return struct.pack('>II', len(entries), 0xFFFFFFFF) + b''.join(struct.pack('>I', e) for e in entries) + b''.join(blobs)


def test_model_textures_in_a_deflated_asset_table():
    ci4 = RED + GREEN + RED*14 + bytes([0x01]*32)
    rgba = (GREEN*16) + bytes(8)                                     # a mip-flagged level, smaller levels after it
    assets = [model([(1, 8, 8, ci4), (0x8004, 4, 4, rgba)]), b'\0\0\0\x05 not a model',
              model([(1, 8, 8, ci4)], first_offset=8)] + [bytes(64)]*14
    image = bytes(32) + asset_table(assets)
    found = rare_models.regions(image)
    assert [(a['asset_index'], len(a['textures'])) for a in found] == [(0, 2)]
    asset = found[0]
    assert [t['preview_settings']['format'] for t in asset['textures']] == ['ci4', 'rgba5551-be']
    assert asset['textures'][1]['mipmapped']
    shown = pixels(base64.b64decode(n64.preview(image, asset, {'texture': 0})['data_url'].split(',')[1]))
    assert shown[:8] == bytes([255, 0, 0, 255, 0, 255, 0, 255])
    assert rare_models.preview(image, asset, {'texture': 1})['details']['width'] == 4
    broken = bytearray(image);broken[asset['offset'] + 4] ^= 0xFF
    with pytest.raises(n64.AssetError, match='Rescan'):rare_models.preview(bytes(broken), asset, {})


def test_a_table_needs_rising_entries():
    table = bytearray(asset_table([model([(1, 8, 8, RED*16 + bytes(32))])] + [bytes(64)]*15))
    table[12:16] = (0xFFFF00).to_bytes(4, 'big')                      # the second entry before the first
    assert rare_models.tables(bytes(table)) == []
