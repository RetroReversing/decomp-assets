import base64
import struct
import zlib

import pytest

from decompassets.formats import AssetError
from decompassets.n64 import offset_textures as texture


def record(*, compressed=True, swapped=False, animated=False):
    frames = []
    for index in range(2 if animated else 1):
        header = bytearray(32)
        header[0:3] = bytes((8, 2, 5))  # IA8
        header[5] = 1
        struct.pack_into('>H', header, 6, 0x400 if swapped else 0)
        header[18] = 2 if animated else 1
        struct.pack_into('>H', header, 22, 48)
        frames.append(bytes(header) + bytes(range(index*16, index*16+16)))
    raw = b''.join(frames)
    if not compressed:
        return raw
    header = bytearray(raw[:32]); header[29] = 1
    compressor = zlib.compressobj(wbits=-15)
    packed = compressor.compress(raw) + compressor.flush()
    result = bytes(header) + len(raw).to_bytes(4, 'little') + b'\x09' + packed
    return result + bytes(-len(result) % 16)


def cartridge():
    entry = record(animated=True, swapped=True)
    data = entry * 16
    offsets = b''.join(struct.pack('>I', i*len(entry)) for i in range(17)) + b'\xff'*4
    offsets += bytes(-len(offsets) % 16)
    sections = [b'', b'', data, offsets, data, offsets] + [b'']*10
    starts = []
    body = b''
    for section in sections:
        starts.append(len(body)); body += section
    table = struct.pack('>I', len(starts)) + b''.join(struct.pack('>I', x) for x in starts)
    return table + bytes(-len(table) % 16) + body


def test_directory_and_animated_frame_previews():
    image = cartridge()
    groups = texture.regions(image)
    assert [group['texture_count'] for group in groups] == [16, 16]
    assert groups[0]['textures'][0]['frames'] == 2
    first = texture.preview(image, groups[0], {'frame': 0})
    second = texture.preview(image, groups[0], {'frame': 1})
    assert first['mime'] == 'image/png'
    assert base64.b64decode(first['data_url'].split(',')[1]).startswith(b'\x89PNG')
    assert first['data_url'] != second['data_url']
    with pytest.raises(AssetError):
        texture.preview(image, groups[0], {'frame': 2})


def test_directory_rejects_corrupt_offsets_and_compressed_data():
    image = bytearray(cartridge())
    pair, = texture.sections(image)
    start, end, _ = pair[0]
    struct.pack_into('>I', image, end+8, 7)
    assert not list(texture.sections(image))
    assert texture.unpack(record()[:40]) is None
    data = bytearray(record(compressed=False)); data[0] = 0
    assert not texture.frames(data)
