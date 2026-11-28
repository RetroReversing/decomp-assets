import struct

import pytest

from decompassets import formats
from decompassets.n64 import float_model_banks as banks


def bank():
    data = bytearray(12 + 2 * (32 + 3 * 24 + 32))
    struct.pack_into('>III', data, 0, 2, 12, 148)
    for start in (12, 148):
        struct.pack_into('>HHII', data, start + 20, 3, 1, start + 32, start + 104)
        for i, point in enumerate(((0., 0., 0.), (1., 0., 0.), (0., 1., 0.))):
            struct.pack_into('>3f', data, start + 32 + i * 24, *point)
        data[start + 108:start + 111] = b'\x00\x01\x02'
    return data


def test_bank_recognition_and_selected_geometry():
    data = bank()
    asset, = banks.regions(data)
    assert asset['nodes'] == 2
    assert (asset['vertices'], asset['triangles']) == (6, 2)
    preview = banks.preview(data, asset, {'mesh': 1})
    assert preview['vertices'] == [(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)]
    assert preview['surfaces'][0]['indices'] == (0, 1, 2)


def test_rejects_invalid_index_and_stale_preview():
    data = bank()
    asset, = banks.regions(data)
    data[120] = 9
    assert banks.regions(data) == []
    with pytest.raises(formats.AssetError):
        banks.preview(data, asset, {})


def test_rejects_nan_and_truncated_bank():
    data = bank()
    struct.pack_into('>f', data, 44, float('nan'))
    assert banks.regions(data) == []
    assert banks.regions(bank()[:-1]) == []
