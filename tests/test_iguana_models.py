import struct

import pytest

from decompassets import formats
from decompassets.n64 import iguana_textures, preview

from .test_rnc import literal_block


def fixture(bad_index=False):
    header = b'!IgUaNa!' + bytes(44)
    vertices = b''.join(struct.pack('<3h8x', *point) for point in [(0, 0, 0), (16, 0, 0), (0, 16, 0)])
    commands = bytes([4, 0, 0, 3, 0, 6, 0, 1, 3 if bad_index else 2, 0, 1])
    directory = struct.pack('<32s6I', b'qvert', 0xcdcdcdcd, 14, 3, 0, 0, len(header))
    directory += struct.pack('<32s6I', b'qcmd', 0xcdcdcdcd, 1, len(commands), 0, 0, len(header)+len(vertices))
    decoded = header+vertices+commands+directory
    packed = literal_block(decoded)[18:]
    payload = packed+bytes(len(packed)%2)
    return struct.pack('>4sIIH4xH', b'RNC\x81', len(decoded), len(payload), 1, len(packed))+payload


def test_iguana_model_uses_loaded_vertex_indices():
    image = fixture()
    models=[]
    assert not iguana_textures.regions(image,models=models)
    asset, = models
    assert asset['offset']==20 and asset['container_offset']==0
    result = preview(image,asset,{'mesh':0})
    assert result['vertices']==[(0, 0, 0), (16, 0, 0), (0, 16, 0)]
    assert result['triangles']==1 and result['edges']==[(0,1),(0,2),(1,2)]
    with pytest.raises(formats.AssetError):
        preview(image,asset,{'mesh':1})
    models.clear()
    iguana_textures.regions(fixture(bad_index=True),models=models)
    assert not models
