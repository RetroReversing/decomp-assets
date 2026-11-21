import struct

import pytest

from decompassets.n64 import audio, compact_midi, uv_sequences


def _sequence(track):
    return struct.pack('>17I', 68, *([0]*15), 48)+track


def test_compact_midi_running_status_and_shared_phrase():
    # Restate the first event from the physical bytes behind the marker.
    track = bytes.fromhex('00 90 3c 60 18 18 40 50 18 fe 00 09 05 00 ff 2f')
    division, events = compact_midi.sequence(_sequence(track))
    assert division == 48
    assert [(event.tick, event.data, event.duration) for event in events] == [
        (0, (60, 96), 24), (24, (64, 80), 24), (24, (60, 96), 24)]
    assert compact_midi.sequence(_sequence(track.replace(b'\xfe\x00\x09', b'\xfe\x00\x02'))) is None


def test_uv_music_directory_checks_sequence_bounds():
    content = _sequence(bytes.fromhex('00 90 3c 60 18 00 ff 2f'))
    bank = b'S1'+struct.pack('>HII', 1, 12, len(content))+content
    form = b'UVMSSEQS'+struct.pack('>I', len(bank))+bank
    image = b'FORM'+struct.pack('>I', len(form))+form
    (_, _, rows), = uv_sequences.directories(image)
    assert rows[0]['notes'] == 1 and rows[0]['division'] == 48
    assert not list(uv_sequences.directories(image[:-1]))


def test_voice_selection_uses_channel_controllers_and_bank_keymap():
    sample = {'relative_offset': 0}
    voice = dict(sample=sample, key_range=(60, 65), velocity_range=(20, 127),
                 key_base=60, detune=0, volume=1, pan=64)
    note = compact_midi.Event(1, 0x92, (62, 127), 10)
    events = [compact_midi.Event(0, 0xc2, (4,)), compact_midi.Event(0, 0xb2, (10, 0)),
              compact_midi.Event(0, 0xb2, (7, 64)), note, compact_midi.Event(2, 0x92, (59, 127), 10)]
    matched, missing = uv_sequences.note_voices(events, {(0, 4): [voice]})
    assert matched == (note, dict(sample=sample, pitch=2, gain=64/127, pan=0))
    assert missing[1] is None


@pytest.mark.parametrize('sequence_first', [False, True])
def test_music_form_uses_adjacent_named_bank_for_stereo_preview(sequence_first):
    import base64
    import io
    import wave

    from .test_native_audio import fixture

    def chunk(tag, data):
        return tag+struct.pack('>I', len(data))+data

    image, _, base = fixture(raw=True)
    bank = chunk(b'FORM', b'UVMB'+chunk(b'PAD ', bytes(8))+
                 chunk(b'.CTL', image[128:base])+chunk(b'.TBL', image[base:]))
    song = _sequence(bytes.fromhex('00 90 3c 60 18 00 ff 2f'))
    sequence = chunk(b'FORM', b'UVMS'+chunk(b'SEQS', b'S1'+struct.pack('>HII', 1, 12, len(song))+song))
    rom = b"\0\0"+sequence+bank if sequence_first else bank+sequence
    assert audio.regions(rom)[0]['table_confidence'] == 'validated'
    asset, = uv_sequences.regions(rom)
    assert asset['samples'][0]['preview_available']
    result = uv_sequences.preview(rom, asset, {'sample': 0})
    with wave.open(io.BytesIO(base64.b64decode(result['data_url'].split(',')[1]))) as output:
        assert output.getnchannels() == 2
        assert output.getframerate() == 22050
        assert any(output.readframes(output.getnframes()))
    assert result['details']['mixed_notes'] == 1
    assert result['details']['skipped_notes'] == 0


def test_standalone_music_directory_follows_sample_extent():
    from decompassets.n64 import audio

    from .test_native_audio import fixture

    image, _, base = fixture()
    song = _sequence(bytes.fromhex('00 90 3c 60 18 00 ff 2f'))
    sequence = b'S1'+struct.pack('>HII', 1, 12, len(song))+song
    # Trim unused fixture tail to the sample's exact extent, then align.
    rom = image[:base+58]+bytes(2)+sequence
    asset, = uv_sequences.regions(rom, sound_banks=audio.regions(rom))
    assert asset['table_offset'] == base
    assert uv_sequences.preview(rom, asset, {'sample': 0})['details']['mixed_notes'] == 1
    shifted = image[:base+58]+bytes(6)+sequence
    assert not uv_sequences.regions(shifted, sound_banks=audio.regions(shifted))
