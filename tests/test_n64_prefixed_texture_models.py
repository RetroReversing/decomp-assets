import struct
import zlib

import pytest

from decompassets.formats import AssetError
from decompassets.n64 import prefixed_texture_models as models


def _model():
    data = bytearray(72 + 3*16)
    struct.pack_into('>6I', data, 0, 1, 24, 1, 56, 1, 72)
    struct.pack_into('>4I', data, 32, 0x01003006, 72, 0x05000204, 0)
    struct.pack_into('>II', data, 48, 0x200, 32)
    struct.pack_into('>4I', data, 56, 0, 0x10000, 0, 48)
    for i, point in enumerate(((0, 0, 0), (10, 0, 0), (0, 10, 0))):
        struct.pack_into('>3h', data, 72 + i*16, *point)
    return bytes(data)


def test_model_batches_and_preview():
    data = _model()
    found = models.models(data)
    assert len(found) == 1
    number, pieces = found[0]
    assert number == 0 and pieces[0][1] == [(0, 1, 2)]
    z = zlib.compressobj(wbits=-15)
    image = struct.pack('>I', len(data)) + z.compress(data) + z.flush()
    item = dict(number=0, vertices=3, triangles=1, label='Model')
    asset = dict(offset=0, size=len(image), meshes=[item], preview_settings={'format': 'auto'})
    out = models.preview(image, asset, {})
    assert out['triangles'] == 1 and out['surfaces'][0]['indices'] == (0, 1, 2)
    with pytest.raises(AssetError):
        models.preview(image[:-1], asset, {})


def test_model_rejects_invalid_vertices_and_batch_bounds():
    data = bytearray(_model())
    struct.pack_into('>I', data, 36, 73)
    assert not models.models(data)
    data = bytearray(_model())
    struct.pack_into('>I', data, 52, 48)
    assert not models.models(data)


def test_model_group_has_browser_counts(monkeypatch):
    data = _model()
    z = zlib.compressobj(wbits=-15)
    image = struct.pack('>I', len(data)) + z.compress(data) + z.flush()
    monkeypatch.setattr(models.prefixed_texture_catalog, 'catalogs', lambda *_args: [[(0, len(image))]])
    group, = models.regions(image)
    assert (group['vertices'], group['triangles']) == (3, 1)
    assert group['meshes'][0]['name']
