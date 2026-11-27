import struct

import pytest

from decompassets import formats
from decompassets.n64 import rnc_pgd_models as models

from .test_rnc import literal_block
from .test_rnc_shpn_images import _method2


def fixture():
    data = bytearray(0xa4 + 0x54 + 18)
    data[:4] = b'PGD\x01'
    struct.pack_into('>5I', data, 0x24, 1, 1, 0, 3, 3)
    struct.pack_into('>I', data, 0x48, 0x54)
    struct.pack_into('>I', data, 0x50, 0x54)
    for i in range(3):
        struct.pack_into('>4H', data, 0xa4 + 0x3c + 8*i, 0, 1, 2, 0)
    struct.pack_into('>9h', data, 0xa4 + 0x54, 0, 0, 0, 10, 0, 0, 0, 10, 10)
    return data


@pytest.mark.parametrize('pack', [literal_block, _method2])
def test_compressed_mesh_preview_and_corruption(pack):
    raw = fixture()
    image = pack(raw)
    asset, = models.regions(image)
    result = models.preview(image, asset, {})
    assert result['vertices'][2] == (0, 10, 10)
    assert result['triangles'] == 3
    raw[0xa4 + 0x3c:0xa4 + 0x3e] = b'\xff\xff'
    assert not models.regions(pack(raw))
    broken = bytearray(image); broken[-1] ^= 1
    with pytest.raises(formats.AssetError):
        models.preview(broken, asset, {})
