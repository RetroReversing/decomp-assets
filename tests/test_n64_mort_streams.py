import base64
import struct

from decompassets import n64
from decompassets.n64 import mort_streams


def clip():
    return struct.pack('>4sHHII', b'MORT', 4, 12000, 4, 7)


def test_consecutive_clips_make_a_playable_bank():
    data = bytes(16) + clip() + clip()
    asset = next(a for a in n64.regions(data) if a.get('layout') == mort_streams.LAYOUT)
    assert asset['sample_count'] == 2
    preview = n64.preview(data, asset, {'sample': 1})
    assert preview['media'] == 'audio'
    assert base64.b64decode(preview['data_url'].split(',', 1)[1]).startswith(b'RIFF')


def test_truncated_or_isolated_clip_is_not_a_bank():
    assert not mort_streams.regions(bytes(16) + clip())
    assert not mort_streams.regions(bytes(16) + clip() + clip()[:-1])
