import base64
import io
import struct
import wave

from decompassets.n64 import audio, lz_standard_midi, preview

from .test_lz_texture_directories import _pack
from .test_native_audio import fixture


def test_lz_song_tables_decode_and_play_with_the_preceding_bank():
    track = bytes.fromhex('00 90 3c 60 30 80 3c 00 00 ff 2f 00')
    song = struct.pack('>4sIHHH4sI', b'MThd', 6, 0, 1, 48, b'MTrk', len(track)) + track
    packed = _pack(song)
    image, _, base = fixture()
    # This fixture's samples end at base+58.
    rom = image[:base+58]+bytes(6)+b'S1'+struct.pack('>HII', 1, 12, len(packed))+packed
    bank = audio.regions(rom)
    asset, = lz_standard_midi.regions(rom, sound_banks=bank)
    assert asset['offset'] == base + 64 and asset['samples'][0]['codec'] == 'Standard MIDI'
    result = preview(rom, asset, {'sample': 0})
    assert result['details']['mixed_notes'] == 1
    with wave.open(io.BytesIO(base64.b64decode(result['data_url'].split(',')[1]))) as wav:
        assert wav.getnchannels() == 2 and any(wav.readframes(wav.getnframes()))
    assert not lz_standard_midi.regions(rom[:-1], sound_banks=bank)
