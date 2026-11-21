import base64

import pytest

from decompassets.formats import AssetError
from decompassets.n64 import rzip_audio


def _frame(cue=False):
    # MPEG-2 Layer III, 64 kbit/s, 22050 Hz, 208 bytes per frame.
    header = bytes((0xff, 0xf3, 0x80, 8 if cue else 0))
    return header + bytes(204) + (b'L:123456\0' if cue else b'')


def test_stream_validates_and_removes_embedded_cues():
    data = _frame(True) + _frame() * 8
    found = rzip_audio.stream(data, preview=True)
    assert found['frames'] == 9
    assert found['rate'] == 22050
    assert found['bytes'] == _frame(True)[:208] + _frame() * 8
    assert b'L:123456' not in found['bytes']
    item = dict(offset=0, size=len(data), rate=22050, samples=9 * 576)
    asset = dict(samples=[item], preview_settings=dict(format='auto'))
    result = rzip_audio.preview(data, asset, {})
    assert result['mime'] == 'audio/mpeg'
    assert base64.b64decode(result['data_url'].split(',')[1]) == found['bytes']
    with pytest.raises(AssetError):
        rzip_audio.preview(data[:-1], asset, {})


def test_stream_rejects_damaged_frames_and_cues():
    assert rzip_audio.stream(_frame() * 7) is None
    assert rzip_audio.stream((_frame() * 8)[:-1]) is None
    broken = bytearray(_frame(True) + _frame() * 8)
    broken[208] = 0
    assert rzip_audio.stream(broken) is None
