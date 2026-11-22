"""Direct EAD directories must bound each control and wave range."""

import struct

from decompassets.n64 import ead_direct_audio, uso_audio


def test_checked_directories_and_selectable_sample(monkeypatch):
    data = bytearray(0x180)
    for at in (0x20, 0x60, 0x80):
        struct.pack_into('>H', data, at, 1)
    struct.pack_into('>II8B', data, 0x30, 0, 0x40, 2, 0, 0, 255, 1, 0, 0, 0)
    struct.pack_into('>II8B', data, 0x70, 0, 0x20, 2, 0, 0, 0, 0, 0, 0, 0)
    struct.pack_into('>II8B', data, 0x90, 0, 0x20, 2, 0, 0, 0, 0, 0, 0, 0)
    struct.pack_into('>6I', data, 0xa0, 0x100, 0x140, 0x160, 0x180, 0x140, 0x160)
    sample = uso_audio._Sample(offset=0, size=9, book=8, predictors=1)
    monkeypatch.setattr(uso_audio, '_groups', lambda *args, **kwargs: [[sample]])
    banks = ead_direct_audio.regions(data)
    assert len(banks) == 1 and len(banks[0]['samples']) == 1
    assert ead_direct_audio.preview(data, banks[0], {'sample': 0})['media'] == 'audio'
    struct.pack_into('>I', data, 0xa4, 0x141)
    assert not list(ead_direct_audio.directories(data))
