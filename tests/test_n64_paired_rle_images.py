"""Bounded paired-directory images and their vertical tile layout."""
import base64
import mmap
import struct
import zlib

from decompassets import n64
from decompassets.n64 import paired_rle_images as images


def fixture():
    raw = bytearray(b'\0\1' * (images._PIXELS//2))
    raw[31*128:31*128+2] = bytes.fromhex('f801')
    raw[:2] = bytes.fromhex('07c1')
    stream = bytearray()
    for at in range(0, len(raw), 31):
        part = raw[at:at+31]
        stream.append(0x80+len(part))
        stream.extend(part)
    block = struct.pack('>I', len(stream)+4) + stream + b'\0'
    data = bytearray(0x1000+len(block)+16*8)
    data[0x400:0x400+len(images._DECODER[0])] = images._DECODER[0]
    data[0x500:0x500+len(images._DECODER[1])] = images._DECODER[1]
    pointers = [0x1000, 0x1000+len(block)] + [0x1000+len(block)+8*i for i in range(1, 16)]
    for i, pointer in enumerate(pointers):
        struct.pack_into('>II', data, 0x100+i*8, pointer, pointer | 0x80000000)
    data[0x1000:0x1000+len(block)] = block
    return bytes(data), bytes(raw)


def _png_rows(data_url):
    png = base64.b64decode(data_url.split(',')[1])
    at = 8
    packed = bytearray()
    while at < len(png):
        size, = struct.unpack_from('>I', png, at)
        if png[at+4:at+8] == b'IDAT':
            packed.extend(png[at+8:at+8+size])
        at += 12+size
    return zlib.decompress(packed)


def test_directory_and_decoder_recover_vertically_flipped_tiles():
    image, raw = fixture()
    assets = images.regions(image)
    assert len(assets) == 1
    assert images.decode(image[assets[0]['offset']:assets[0]['offset']+assets[0]['size']]) == raw
    rows = _png_rows(n64.preview(image, assets[0], {})['data_url'])
    stride = 1+320*4
    assert rows[1:5] == bytes((255, 0, 0, 255))
    assert rows[31*stride+1:31*stride+5] == bytes((0, 255, 0, 255))


def test_unproven_directory_and_corrupt_stream_are_not_previews():
    image, _ = fixture()
    damaged = bytearray(image)
    damaged[0x400] = 0
    assert images.regions(damaged) == []
    damaged = bytearray(image)
    damaged[0x1000+4:0x1000+6] = b'\x00\x00'  # invalid zero-distance backreference
    assert images.regions(damaged) == []


def test_rom_scanner_accepts_a_memory_mapped_image(tmp_path):
    image, _ = fixture()
    path = tmp_path/'game.bin'
    path.write_bytes(image)
    with path.open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
        assert images.regions(mapped) == images.regions(image)
