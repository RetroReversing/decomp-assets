import base64
import struct
import zlib

import pytest

from decompassets.formats import AssetError
from decompassets.n64 import packed_tim, preview, regions

# A hand-built directory with two images. The indexed image has two palettes.
_BANK = bytes.fromhex(
    '0000008ae7737b3bfc660dfce60baeff5f7d85aead6b652d6b762d3335553ab1d555abaaaaaa6db6e'
    '492492492492494cc7c924900001555555cd2aab8d4d9349e54ed5315552e9a4e9610'
)


def _rgba(result):
    png = base64.b64decode(result['data_url'].split(',')[1])
    size = struct.unpack_from('>I', png, 33)[0]
    return zlib.decompress(png[41:41 + size])[1:]


def test_detected_images_preview_with_palette_and_member_selection():
    image = bytes(16) + _BANK + bytes(32)
    asset, = [row for row in regions(image) if row['layout'] == packed_tim.LAYOUT]
    assert (asset['offset'], asset['size']) == (16, len(_BANK))
    assert [texture['palettes'] for texture in asset['textures']] == [2, 0]
    assert _rgba(preview(image, asset, {})) == bytes((255, 0, 0, 255)) + bytes(12)
    assert _rgba(preview(image, asset, {'palette': 1})) == bytes((0, 255, 0, 255)) + bytes(12)
    assert _rgba(preview(image, asset, {'texture': 1})) == bytes((255, 0, 0, 255, 0, 0, 255, 255))
    with pytest.raises(AssetError, match='Palette'):
        preview(image, asset, {'palette': 2})


def test_compressed_prefix_alone_does_not_validate_archive():
    assert packed_tim.regions(_BANK[:-5]) == []
    bank, _ = packed_tim._unpack(_BANK[4:], 138, lambda: None)
    bank[15] += 1
    assert not packed_tim._members(bank)


def test_overlapping_match_obeys_declared_size():
    stream = bytes.fromhex('058c0000')
    assert packed_tim._unpack(stream, 4, lambda: None)[0] == b'yyyy'
    with pytest.raises(AssetError, match='declared size'):
        packed_tim._unpack(stream, 3, lambda: None)
