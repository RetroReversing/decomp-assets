"""Build a synthetic archive whose pixels and short palette share a member."""

import struct

from decompassets.n64 import paged_lz, paged_textures, preview


def _packed(data):
    literals = b''.join(b'\xff' + data[start:start+8] for start in range(0, len(data), 8))
    return struct.pack('>I', len(data)) + literals


def _archive(member):
    return struct.pack('>4I', 0x2008, 1024, 0, len(member)) + b'\xff' * (1023*8) + member


def test_paged_texture_archive_validates_palette_and_preview():
    member = struct.pack('>4s8I', b'64\x008', 2, 0, 18, 0x30002, 36, 26, 3, 40)
    pixels = bytes.fromhex('0120 2100')
    palette = bytes.fromhex('f801 07c1 003f')
    image = _archive(_packed(member + pixels + palette))
    bank, = paged_textures.regions(image)
    assert bank['texture_count'] == 1
    result = preview(image, bank, {'texture': 0})
    assert result['media'] == 'image'
    assert (result['details']['width'], result['details']['height']) == (3, 2)

    malformed_pixels = bytes.fromhex('0120 3100')
    assert not paged_textures.regions(_archive(_packed(member + malformed_pixels + palette)))
    assert not paged_textures.regions(image[:-1])


def test_paged_lz_wraps_offsets_and_rejects_oversized_matches():
    # First literal writes at 0x3be. A back-reference repeats it via the ring.
    packed = struct.pack('>I', 4) + bytes.fromhex('0142bec0')
    assert paged_lz.unpack(packed) == b'BBBB'
    assert paged_lz.unpack(struct.pack('>I', 3) + packed[4:]) is None


def test_inline_numeric_text_is_not_a_resource_pointer():
    header = struct.pack('>4s8I', b'64\x008', 2, 0, 4, 0, int.from_bytes(b'0.50', 'big'), 25, 0x10001, 36)
    member = _archive(_packed(header + bytes.fromhex('ff0000ff')))
    texture, = paged_textures.regions(member)
    assert texture['textures'][0]['preview_settings']['format'] == 'rgba8888'


def test_paged_model_resolves_segment_two_and_keeps_mesh_selection():
    from decompassets.n64 import paged_lz_models

    header = struct.pack('>4s8I', b'64\x008', 2, 0, 0, 0x3f800000, 40, 4, 0, 0)
    commands = struct.pack('>8I', 0x04000c2f, 0x02000048,
                           0xbe000000, 4, 0xbf000000, 0x00000204, 0xb8000000, 0)
    vertices = b''.join(struct.pack('>3hH2h4B', x, y, 0, 0, 0, 0, 255, 255, 255, 255)
                        for x, y in ((0, 0), (1, 0), (0, 1)))
    image = _archive(_packed(header + bytes(4) + commands + vertices))
    bank, = paged_lz_models.regions(image)
    assert len(bank['meshes']) == 1
    result = preview(image, bank, {'mesh': 0})
    assert result['triangles'] == 1
    assert result['vertices'] == [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
    assert result['settings']['mesh'] == 0
