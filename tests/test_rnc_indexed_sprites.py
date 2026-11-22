import base64
import struct

from decompassets.n64 import rnc_indexed_sprites as sprites


def record():
    header = struct.pack('<3H', 4, 4, 0)+bytes(26)
    palette = struct.pack('<16H', *range(16))
    return header+palette+b'\x21'*8


def test_bounded_sprite_records_and_preview(monkeypatch):
    data = record()+record()+struct.pack('<3H', 8, 8, 0)+bytes(26)
    assert len(sprites.frames(data)) == 2
    assert not sprites.frames(data[:-1])
    monkeypatch.setattr(sprites.rnc, 'unpack_at', lambda *_: (data, 12))
    asset = dict(offset=0, reason='Palette order is inferred.', preview_settings={'offset': 0})
    result = sprites.preview(b'', asset, {'frame': 1})
    assert result['details']['width'] == 4
    assert base64.b64decode(result['data_url'].split(',')[1]).startswith(b'\x89PNG')
