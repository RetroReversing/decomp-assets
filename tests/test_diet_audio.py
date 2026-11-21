"""Synthetic DIET and Standard MIDI blocks, including a packed predictor book."""

import struct

import pytest

from decompassets import n64
from decompassets.formats import AssetError
from decompassets.n64 import diet, diet_audio, standard_midi

from .test_native_audio import fixture, wav


def _pack(data):
    payload = bytearray(2)
    flags = cursor = 0

    def bit(value):
        nonlocal flags, cursor
        payload[flags+cursor//8] |= value<<(cursor%8)
        cursor += 1
        if cursor == 16:
            flags, cursor = len(payload),0
            payload.extend(bytes(2))

    for value in data:
        bit(1)
        payload.append(value)
    bit(0)
    bit(0)
    payload.append(255)
    bit(0)
    bit(0)
    crc = 0
    for value in payload:
        for _ in range(8):
            crc = (crc>>1) ^ (0xa001 if (crc^value)&1 else 0)
            value >>= 1
    return diet.MAGIC+bytes(1)+struct.pack('<HHBH',len(payload),crc,0,len(data))+payload


def _midi(track):
    return struct.pack('>4sIHHH4sI',b'MThd',6,0,1,480,b'MTrk',len(track))+track


def test_diet_validates_crc_before_decoding():
    packed = _pack(bytes(range(32)))
    assert diet.unpack(packed,0) == (bytes(range(32)),len(packed))
    with pytest.raises(AssetError,match='checksum'):
        diet.unpack(packed[:-1]+bytes([packed[-1]^1]),0)
    with pytest.raises(AssetError,match='extent'):
        diet.unpack(packed[:-1],0)


def test_standard_midi_uses_running_status_and_note_off():
    midi = _midi(bytes.fromhex('00 c0 00 00 90 3c 60 81 70 3c 00 00 ff 2f 00'))
    division, events = standard_midi.sequence(midi)
    assert division == 480
    assert events[1].duration == 240 and events[1].data == (60,96)
    assert standard_midi.sequence(midi[:-1]) is None


def test_packed_bank_and_song_use_the_decoded_adpcm_book():
    raw,_,table = fixture()
    control = _pack(raw[128:table])
    control += bytes(-len(control)%16)
    midi = _midi(bytes.fromhex('00 90 3c 7f 81 70 80 3c 00 00 ff 2f 00'))
    image = control+raw[table:table+64]+_pack(midi)
    bank,song = diet_audio.regions(image)
    for asset in (bank,song):
        _,frames = wav(n64.preview(image,asset,{'sample':0}))
        assert any(frames)
    corrupted = bytearray(image)
    corrupted[len(control)]=0xff
    assert not diet_audio.regions(corrupted)
