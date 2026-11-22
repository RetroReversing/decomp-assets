import struct

from decompassets.n64 import edl, edl_textures


def _stream(data):
    result = b'EDL\x80' + struct.pack('>II', len(data) + 12, len(data)) + data
    return result + b'\0' * (-len(result) % 16)


def test_adjacent_components_expose_bounded_textures():
    child = struct.pack('>I', 0x40000003) + b'\0' * 6
    metadata = (struct.pack('>H', 4) + struct.pack('>5H', 0, 4, 4, 0, 2) + child * 2
                + struct.pack('>5H', 2, 4, 4, 0, 2) + child * 2)
    components = [_stream(metadata), _stream(bytes(range(32))), _stream(b'abcde')]
    image = b''.join(components) + b'\xff\xff' * 256
    offsets = [0, len(components[0]), len(components[0]) + len(components[1])]
    blocks = {offset: edl.header(image, offset)[:3] for offset in offsets}
    assets = edl_textures.regions(image, blocks, lambda: None)
    assert len(assets) == 1
    assert assets[0]['texture_count'] == 2
    preview = edl_textures.preview(image, assets[0], {'texture': 1})
    assert preview['media'] == 'image'
    assert preview['details']['width'] == 4
    assert preview['details']['format'] == 'CI8'
    assert edl_textures.regions(image[:-2], blocks, lambda: None) == []
