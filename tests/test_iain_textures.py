"""Exercise Iain block decoding and texture selection with generated data."""

import base64
import struct
import zlib

import pytest

from decompassets.formats import AssetError
from decompassets.n64 import iain, preview


def _archive(size, blocks):
    header = bytearray(struct.pack('>4sII', b'Iain', size, len(blocks)) + bytes(0x180))
    output = bytearray()
    for index, (mode, data) in enumerate(blocks):
        span = (len(data) + 3) & ~3
        struct.pack_into('>I', header, 12 + index * 4, len(header) + len(output))
        struct.pack_into('>H', header, 0x10c + index * 2, span)
        output.extend(struct.pack('>HH', mode, len(data)) + data.ljust(span, b'\0'))
    return header + output


def test_iain_block_bounds_and_backreferences():
    compressed = b'\0' * 4 + b'\x02\0A\x04\x01'
    raw = b'\x01\0\0\0BC'
    image = _archive(9, [(1, compressed), (1, raw), (0, b'D')])
    assert iain.unpack(image, 0) == (b'AAAAAABCD', len(image))
    assert iain.unpack(image[:-1], 0) is None
    assert iain.unpack(_archive(5, [(1, compressed)]), 0) is None
    assert iain.unpack(_archive(6, [(1, compressed[:-1] + b'\x02')]), 0) is None


def test_iain_texture_bank_previews_each_named_image():
    bank = (struct.pack('>I', 2) + b'Light\0' + struct.pack('>3H', 2, 1, 28) + bytes.fromhex('f80107c1')
            + b'Shade\0' + struct.pack('>3H', 1, 1, 3) + b'\xa5')
    image = _archive(len(bank), [(0, bank)])
    asset, = iain.regions(image)
    assert [item['label'] for item in asset['textures']] == ['Light', 'Shade']
    assert preview(image, asset, {})['details']['width'] == 2
    result = preview(image, asset, {'texture': 1})
    assert result['settings']['texture'] == 1
    png = base64.b64decode(result['data_url'].split(',', 1)[1])
    length, = struct.unpack_from('>I', png, 33)
    assert png[37:41] == b'IDAT'
    assert zlib.decompress(png[41:41 + length]) == bytes((0, 170, 170, 170, 85))
    with pytest.raises(AssetError, match='Texture'):
        preview(image, asset, {'texture': 2})

    assert not iain.regions(_archive(len(bank) + 1, [(0, bank + b'\0')]))


def test_iain_scene_meshes_use_local_faces_and_vertex_colors():
    def mesh(label, face):
        vertices = b''.join(struct.pack('>5fx3B', x, y, 0, 0, 0, 10, 20, 30)
                            for x, y in ((0, 0), (1.5, 0), (0, 2)))
        return struct.pack('>I2H44x', 0, 3, 1) + label + b'\0' + vertices + struct.pack('>3H8x', *face)

    header = b'\0\x01paint\0' + struct.pack('>I', 2)
    data = header + mesh(b'First', (0, 1, 2)) + mesh(b'Second', (1, 0, 2))
    image = _archive(len(data), [(0, data)])
    bank, = iain.regions(image)
    assert [item['label'] for item in bank['meshes']] == ['First', 'Second']
    result = preview(image, bank, {'mesh': 1})
    assert result['vertices'] == [(0, 0, 0), (1.5, 0, 0), (0, 2, 0)]
    assert result['edges'] == [(0, 1), (0, 2), (1, 2)]
    assert result['surfaces'][0]['indices'] == (1, 0, 2)
    assert result['surfaces'][0]['colors'] == [(10, 20, 30, 255)] * 3
    assert result['settings']['mesh'] == 1

    invalid = header + mesh(b'First', (0, 1, 2)) + mesh(b'Invalid', (1, 0, 3))
    assert not iain.regions(_archive(len(invalid), [(0, invalid)]))
