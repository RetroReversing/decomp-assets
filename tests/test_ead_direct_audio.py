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


def test_consecutive_tables_and_payloads_provide_checked_sample_banks():
    data = bytearray(0x270)
    struct.pack_into('>H', data, 0x20, 3)
    for index in range(3):
        struct.pack_into('>II8B', data, 0x30 + index*16, index*0x60, 0x60, 2, 0, 0, 255, 1, 0, 0, 0)
    struct.pack_into('>3H', data, 0x60, 6, 8, 10)
    data[0x66:0x6c] = bytes((1, 0, 1, 1, 1, 2))
    struct.pack_into('>H', data, 0x70, 3)
    for index in range(3):
        struct.pack_into('>II8B', data, 0x80 + index*16, index*0x10, 0x10, 2, 0, 0, 0, 0, 0, 0, 0)
    struct.pack_into('>H', data, 0xb0, 2)
    for index in range(2):
        struct.pack_into('>II8B', data, 0xc0 + index*16, index*0x20, 0x20, 2, 0, 0, 0, 0, 0, 0, 0)
    for index in range(3):
        control = 0xe0 + index*0x60
        struct.pack_into('>6I', data, control+16, 9, 0, 72, 32, 2, 1)
        struct.pack_into('>3I', data, control+72, 0, 16, 0)
    banks = ead_direct_audio.regions(data)
    assert len(banks) == 1 and banks[0]['samples'][0]['offset'] == 0x200
    assert ead_direct_audio.preview(data, banks[0], {'sample': 0})['media'] == 'audio'
    # A broken font map prevents a coincidental set of tables from claiming audio.
    data[0x67] = 3
    assert not list(ead_direct_audio.contiguous_directories(data))


def test_filesystem_payloads_and_aliased_sample_bank(monkeypatch):
    data = bytearray(0x600)
    struct.pack_into('>H', data, 0x20, 3)
    for index in range(3):
        struct.pack_into('>II8B', data, 0x30 + index*16, index*0x60, 0x60, 2, 0, 1, 255, 1, 0, 0, 0)
    struct.pack_into('>3H', data, 0x60, 6, 8, 10)
    data[0x66:0x6c] = bytes((1, 0, 1, 1, 1, 2))
    struct.pack_into('>H', data, 0x70, 3)
    for index in range(3):
        struct.pack_into('>II8B', data, 0x80 + index*16, index*0x10, 0x10, 2, 0, 0, 0, 0, 0, 0, 0)
    struct.pack_into('>H', data, 0xb0, 2)
    struct.pack_into('>II8B', data, 0xc0, 0, 0x20, 2, 0, 0, 0, 0, 0, 0, 0)
    struct.pack_into('>II8B', data, 0xd0, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0)
    struct.pack_into('>12I', data, 0x100, 0x300, 0x420, 0x300, 0,
                     0x420, 0x450, 0x420, 0, 0x450, 0x470, 0x450, 0)
    sample = uso_audio._Sample(offset=0, size=9, book=8, predictors=1)
    monkeypatch.setattr(uso_audio, '_groups', lambda *args, **kwargs: [[sample]])
    banks = ead_direct_audio.regions(data)
    assert len(banks) == 1 and banks[0]['samples'][0]['offset'] == 0x450
    assert ead_direct_audio.preview(data, banks[0], {'sample': 0})['media'] == 'audio'

    # Compressed or ambiguous filesystem records do not prove the payload locations.
    struct.pack_into('>I', data, 0x10c, 0x420)
    assert not list(ead_direct_audio.filesystem_directories(data))
    struct.pack_into('>I', data, 0x10c, 0)
    data[0x140:0x170] = data[0x100:0x130]
    assert not list(ead_direct_audio.filesystem_directories(data))
