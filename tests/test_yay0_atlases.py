import base64
import struct

import pytest

from decompassets import n64
from decompassets.n64 import yay0_atlases


def test_cached_loader_table_requires_four_non_overlapping_atlases():
    fake = b'Yay0\0\0\x10\0' + bytes(8)
    payload = struct.pack('>8I',0xb0000020,16,0xb0000030,16,0xb0000040,16,0xb0000050,16)
    image = payload+fake*4
    assert yay0_atlases._table(image,0)==[(32,48),(48,64),(64,80),(80,96)]
    assert yay0_atlases._table(image[:-1],0)==[]
    repeated = payload[:8]+payload[:8]+payload[16:]+fake*4
    assert yay0_atlases._table(repeated,0)==[]
    assert yay0_atlases.regions(image)==[]


def test_texture_preview_dispatch_decodes_the_native_ia4_layout():
    crunch64 = pytest.importorskip('crunch64')
    payload = crunch64.yay0.compress(bytes([255])*4096)
    asset = dict(offset=0,size=len(payload),layout=yay0_atlases.LAYOUT,label='Glyph atlas')
    result = n64.preview(payload,asset,{})
    image = base64.b64decode(result['data_url'].split(',',1)[1])
    assert image[:8]==b'\x89PNG\r\n\x1a\n'
    assert struct.unpack_from('>II',image,16)==(128,64)
