import struct

import pytest

from decompassets import n64, rnc
from decompassets.n64 import dean_audio, rnx, rnx_atlas, textures

from .test_rnc_textures import mixed_bank, sum_block


def page(data, tag):
    packed = tag + sum_block(data)[4:]
    return packed + bytes(-len(packed) % 8)


def test_rnx_blocks_follow_relative_alignment_and_verify_every_page():
    first = bytes(range(256)) * 64
    last = b'tail'
    stream = page(first, b'RNX\1') + page(last, b'RNC\1') + b'END!'
    whole = bytes(4) + stream
    assert rnx.unpack(whole, 4) == (first + last, len(stream))
    assert textures.decode(stream) == (first + last, rnx.CODEC)
    damaged = bytearray(stream)
    damaged[15] ^= 1
    for invalid in (damaged, stream[:-1]):
        with pytest.raises(rnc.RncError):
            rnx.unpack(invalid)
    with pytest.raises(rnc.RncError, match='output limit'):
        rnx.unpack(stream, max_output=len(first))


def test_rnx_recognizes_a_texture_bank_with_a_fill_tail():
    base = mixed_bank()
    # A larger second RGBA tile makes the bank span the first 16 KiB page.
    first = base[:16]
    second = struct.pack('>B3sBBBBII', 1, b'\xff' * 3, 64, 64, 6, 6, 288, 288)
    raw = first + second + base[32:288] + bytes(64 * 64 * 4)
    tail = struct.pack('>4sHBB', b'FILL', len(raw) - rnx.PAGE, 0, 0)
    stream = page(raw[:rnx.PAGE], b'RNX\1') + tail + b'END!'
    bank, = rnx.regions(stream)
    assert len(bank['textures']) == 2
    assert n64.preview(rnx.unpack(stream)[0], bank, {'texture': 1})['details']['width'] == 64


def test_atlas_checks_all_boundaries_and_previews_supported_direct_tiles():
    tile = struct.pack('>BBBH', 0,8,8,0) + bytes(32)
    data = (struct.pack('>I',30) + b'\xcd'*6 + struct.pack('>I',62)
            + struct.pack('>BBII',1,1,64,62+len(tile)) + b'\xcd'*6 + b'\xf8\x01'*16 + tile)
    items = rnx_atlas.layout(data)
    assert len(items) == 1
    assert rnx_atlas.preview(data, rnx_atlas.asset(items,0,len(data)), {})['details']['width'] == 8
    assert rnx_atlas.layout(data[:-1]) is None


def test_dean_requires_agreeing_directory_and_stream_metadata():
    stream = struct.pack('>III',11025,1,4) + b'\x01\x02\x03\x04'
    record = b'RAW!' + struct.pack('>I',len(stream)) + stream + b'END!'
    directory = b''.join(struct.pack('>III',24+i*len(record),len(stream),sum(stream)) for i in range(2))
    image = directory + 2*record
    first, second = dean_audio.regions(image)
    assert first['samples'][0]['preview_available'] is False
    assert n64.preview(image, second, {})['fields']['Sample rate (Hz)'] == 11025
    corrupt = bytearray(image)
    corrupt[-5] ^= 1
    assert not dean_audio.regions(corrupt)
    assert not dean_audio.regions(record)
