import struct
import zlib

from decompassets.n64 import indexed_deflate_models as models


def test_model_checks_batch_ranges_and_compressed_extent():
    data = bytearray(0x100)
    struct.pack_into('>3H', data, 0x12, 3, 1, 1)
    struct.pack_into('>3I', data, 0x1c, 0x90, 0xb0, 0xc0)
    struct.pack_into('>3h', data, 0x90, 10, 20, 30)
    data[0xb1:0xb4] = b'\0\1\2'
    struct.pack_into('>2H', data, 0xd6, 3, 1)
    compressed = zlib.compressobj(wbits=-15)
    block = len(data).to_bytes(4, 'little') + b'\x09' + compressed.compress(data) + compressed.flush()
    assert models.unpack(block, 0, len(block)) == data
    vertices, faces = models.geometry(data)
    assert vertices[0] == (10, 20, 30)
    assert faces == [(0, 1, 2)]
    data[0xb3] = 3
    assert models.geometry(data) is None
    assert models.unpack(block[:-1], 0, len(block)-1) is None


def test_texture_decodes_swapped_odd_rows_and_rejects_truncation():
    header = bytearray(0x20)
    header[0:3] = bytes((8, 2, 2))  # 8-bit intensity
    pixels = bytes(range(16))
    image = bytes(header) + pixels
    decoded = models.texture_data(image, 0, len(image))
    assert decoded == (pixels[:8] + pixels[12:16] + pixels[8:12], 8, 2, 'i8')
    asset = dict(offset=0, size=len(image), preview_settings=dict(format='auto', source='rom', offset=0))
    assert models.preview_texture(image, asset, {})['mime'] == 'image/png'
    assert models.texture_data(image[:-1], 0, len(image)-1) is None


def test_archive_scanner_finds_only_valid_model_members():
    model = bytearray(0x100)
    struct.pack_into('>3H', model, 0x12, 3, 1, 1)
    struct.pack_into('>3I', model, 0x1c, 0x90, 0xb0, 0xc0)
    model[0xb1:0xb4] = b'\0\1\2'
    struct.pack_into('>2H', model, 0xd6, 3, 1)
    compressor = zlib.compressobj(wbits=-15)
    block = len(model).to_bytes(4, 'little') + b'\x09' + compressor.compress(model) + compressor.flush()
    # The index has a sentinel end offset and an empty final member.
    table = struct.pack('>4I', 0, len(block), len(block), 0xffffffff)
    sections = [0]*39 + [len(table)] + [len(table)+len(block)]*32
    image = bytearray(0x130) + table + block
    struct.pack_into('>I', image, 0, 71)
    struct.pack_into('>72I', image, 4, *sections)
    found = models.regions(image)
    assert len(found) == 1 and found[0]['triangles'] == 1
    assert models.preview(image, found[0], {})['triangles'] == 1
    image[-1] ^= 0xff
    assert not models.regions(image)
