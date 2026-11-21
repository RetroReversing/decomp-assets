"""Generated tests for paired offsets, token decoding and local texture loads."""

import base64
import struct
import zlib

from decompassets.n64 import paired_resources, preview


def _packed(data):
    parts = [data[index:index + 31] for index in range(0, len(data), 31)]
    payload = b''.join(bytes([0x80 | len(block)]) + block for block in parts)
    return struct.pack('>I', 4 + len(payload)) + payload


def _directory(data):
    members = [_packed(data), *[_packed(b'empty record')] * 7]
    starts = [72]
    for member in members:
        starts.append(starts[-1] + ((len(member) + 1) & ~1))
    return (b''.join(struct.pack('>2I', offset, offset | 0x80000000) for offset in starts)
            + b''.join(member + bytes(len(member) % 2) for member in members))


def _texture():
    indices = bytes([0x01] * 16)
    palette = bytes.fromhex('f801 07c1') + bytes(28)
    commands = (
        (0xfd500000, 0x06000000), (0xf5500000, 0x07000000),
        (0xe6000000, 0), (0xf3000000, 0x07007000), (0xe7000000, 0),
        (0xf5400200, 0), (0xf2000000, 0x0003c004),
        (0xfd100000, 0x06000010), (0xe8000000, 0), (0xf5000100, 0x07000000),
        (0xe6000000, 0), (0xf0000000, 0x0703c000),
    )
    return indices + palette + b''.join(struct.pack('>2I', *command) for command in commands)


def test_paired_resources_reject_truncated_tokens_and_invalid_history():
    tokens = bytes.fromhex('8141 0401 a142 e0 ff03')
    raw = struct.pack('>I', 4 + len(tokens)) + tokens
    assert paired_resources.unpack(raw, 0, len(raw)) == b'AAAABBB' + bytes(7)
    assert paired_resources.unpack(raw[:-1], 0, len(raw)) is None
    assert paired_resources.unpack(bytes.fromhex('00000006 0401'), 0, 6) is None
    assert paired_resources.unpack(bytes.fromhex('00000006 8241'), 0, 6) is None


def test_paired_texture_preview_uses_the_render_tile_and_local_palette():
    asset, = paired_resources.regions(image := _directory(_texture()))
    row, = asset['textures']
    assert row['preview_settings'] == dict(format='ci4', width=16, height=2, offset=0,
                                          palette_offset=16, palette_format='rgba5551-be')
    result = preview(image, asset, {'texture': 0})
    assert result['media'] == 'image'
    assert result['details']['width'] == 16
    png = base64.b64decode(result['data_url'].split(',', 1)[1])
    length, = struct.unpack_from('>I', png, 33)
    scanline = b'\0' + bytes.fromhex('ff0000ff 00ff00ff') * 8
    assert zlib.decompress(png[41:41 + length]) == scanline * 2

    invalid = bytearray(_texture())
    invalid[48 + 7 * 8 + 4] = 9
    assert not paired_resources.regions(_directory(invalid))
    changed = bytearray(image)
    changed[11] ^= 2
    assert not paired_resources.regions(changed)


def _flagged(data):
    payload = zlib.compress(data)
    return struct.pack('>I', 0x80000000 | (4 + len(payload))) + payload


def test_paired_scene_previews_local_display_list_meshes():
    vertices = b''.join(struct.pack('>3hH2h4B', x, y, 0, 0, 0, 0, 255, 255, 255, 255)
                        for x, y in ((0, 0), (8, 0), (0, 8)))
    head = struct.pack('>2I', 0x01003006, 0x06000000)
    end = struct.pack('>2I', 0xdf000000, 0)
    first = head + struct.pack('>2I', 0x05000204, 0) + end
    second = head + struct.pack('>2I', 0x05000402, 0) + end
    image = _directory(vertices + first + second)
    asset, = paired_resources.regions(image)
    assert len(asset['meshes']) == 2
    result = preview(image, asset, {'mesh': 1})
    assert result['vertices'] == [(0, 0, 0), (8, 0, 0), (0, 8, 0)]
    assert result['surfaces'][0]['indices'] == (0, 2, 1)
    assert result['settings']['mesh'] == 1
    assert not paired_resources.regions(_directory(vertices + first[:-8]))
    flagged = _flagged(vertices + first + second)
    asset, = paired_resources.regions(flagged)
    assert asset['codec'] == 'zlib'
    assert preview(flagged, asset, {'mesh': 1})['surfaces'] == result['surfaces']


def test_flagged_zlib_resource_exposes_textures_and_checks_its_exact_extent():
    payload = zlib.compress(_texture())
    image = bytes(2) + _flagged(_texture()) + b'padding'
    asset, = paired_resources.regions(image)
    assert asset['size'] == len(payload) + 4 and asset['codec'] == 'zlib'
    assert preview(image, asset, {'texture': 0})['details']['width'] == 16
    assert not paired_resources.regions(image[:-8])
    assert not paired_resources.regions(bytes(2) + struct.pack('>I', 0x80000000 | (5 + len(payload))) + payload + b'x')
