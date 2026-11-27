"""Only complete, independently checked zlib pages form a container."""
import struct
import zlib

from decompassets import n64
from decompassets.n64 import chunked_zlib, textures


def container(raw):
    blocks = bytearray()
    for at in range(0,len(raw),16000):
        packed = zlib.compress(raw[at:at+16000])
        blocks.extend(struct.pack('>I',len(packed))+packed)
        if len(blocks) & 1:
            blocks.append(0)
    return struct.pack('>II',len(blocks)+8,len(raw))+blocks


def test_validate_and_decode_complete_multiple_pages():
    raw = bytes(range(256))*75
    data = container(raw)
    assert chunked_zlib.unpack(data) == (raw,len(data),2)
    asset, = chunked_zlib.regions(data)
    assert asset['expanded_size'] == len(raw)
    assert n64.preview(data,asset,{})['media'] == 'metadata'
    assert textures.decode(data) == (raw,chunked_zlib.CODEC)


def test_reject_bad_checksum_lengths_padding_and_truncation():
    data = container(bytes(range(256))*75)
    corrupt = bytearray(data)
    corrupt[20] ^= 1
    assert chunked_zlib.unpack(corrupt) is None
    assert chunked_zlib.unpack(data[:-1]) is None
    bad = bytearray(data)
    bad[7] ^= 1
    assert chunked_zlib.unpack(bad) is None
    bad = bytearray(data)
    bad[11] = 0
    assert chunked_zlib.unpack(bad) is None
    padded = container(b'x'*32)
    first = int.from_bytes(padded[8:12],'big')
    if (12+first) & 1:
        bad = bytearray(padded)
        bad[-1] = 1
        assert chunked_zlib.unpack(bad) is None


def test_manual_texture_can_reverse_rows_without_reversing_pixels():
    from decompassets import formats

    options = {'format':'i8','width':2,'height':2,'offset':0}
    raw = bytes([1, 2, 3, 4])
    normal, _ = formats.texture_pixels(raw,options)
    flipped, _ = formats.texture_pixels(raw,{**options,'flip_y':True})
    assert flipped == normal[8:16]+normal[0:8]
