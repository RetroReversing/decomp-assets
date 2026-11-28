"""Adjacent named MIDI tracks use only synthetic bank and score bytes."""
import struct

from decompassets.n64 import audio, named_record_midi

from .test_diet_audio import _midi
from .test_native_audio import fixture, wav


def record(name, data, padding=b''):
    return struct.pack('>II', len(data)+len(padding)+24, 0)+name.ljust(16, b'\0')+data+padding


def test_named_midi_records_resolve_through_preceding_sound_bank():
    source, _, base = fixture()
    controls, waves = source[128:base], source[base:]
    midi = _midi(bytes.fromhex('00 90 3c 7f 81 70 80 3c 00 00 ff 2f 00'))
    song = record(b'first.mid', midi, b'\x11\x22')
    image = bytes(128)+record(b'music.tbl', waves)+record(b'music.ctl', controls)+song+record(b'second.mid', midi)
    banks = audio.regions(image)
    rows = named_record_midi.regions(image, sound_banks=banks)
    assert len(rows) == 1 and len(rows[0]['samples']) == 2
    for i in (0, 1):
        _, frames = wav(named_record_midi.preview(image, rows[0], {'sample': i}))
        assert any(frames)
    assert not named_record_midi.regions(image[:-len(record(b'second.mid', midi))], sound_banks=banks)
    damaged = bytearray(image)
    damaged[rows[0]['offset']+24] ^= 1
    assert not named_record_midi.regions(damaged, sound_banks=banks)
