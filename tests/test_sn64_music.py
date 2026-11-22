import base64
import io
import struct
import wave

from decompassets import n64
from decompassets.n64 import sn64, sn64_music


def music_fixture():
    patch = struct.pack('<H', 1) + struct.pack('>H', 0)
    voice = bytearray(20)
    voice[:8] = bytes([100, 127, 64, 1, 60, 0, 0, 127])
    voice[18] = 127
    wave = struct.pack('>6I', 0, 18, 0, 0, 0xffffffff, 0)
    loops = struct.pack('>4H', 1, 0, 0, 1)
    book = struct.pack('>2I256s', 2, 1, bytes(256))
    body = patch + bytes(4) + voice + bytes(4) + wave + loops + book
    bank = struct.pack('>4s8I6H2I', b'SN64', 2, 0, 100, 0, 0, len(body), 0,
                       1, 1, 4, 1, 20, 1, 24, 0, 0) + body
    bank += bytes(-len(bank) % 16)
    events = bytes.fromhex('00 11 3c 7f 10 12 3c 00 22')
    track = struct.pack('>HHHBBHHHHHH', 0x100, 0, 0, 127, 64, 0, 120, 120, 0, 0, len(events)) + events
    seq = struct.pack('>4s7I', b'SSEQ', 2, 0, 1, 0, 0, 16, 0)
    seq += struct.pack('>HHIII', 1, 0, len(track), 0, 0) + track
    seq += bytes(-len(seq) % 16)
    return bank + seq + (bytes([0]) + bytes([0x77]) * 8) * 2


def test_sequence_tracks_pair_notes_and_reject_bad_commands():
    image = music_fixture()
    directory = next(a for a in sn64.regions(image) if a['layout'] == 'sn64-sequences')
    division, events = sn64_music.sequence(image, directory['sequences'][0])
    assert division == 120
    [note] = [e for e in events if e.status & 0xf0 == 0x90]
    assert (note.tick, note.data, note.duration) == (0, (60, 127), 16)
    broken = bytearray(image)
    broken[directory['sequences'][0]['offset'] + 21] = 0xff
    assert sn64_music.sequence(broken, directory['sequences'][0]) is None


def test_sequence_preview_mixes_validated_bank_samples():
    image = music_fixture()
    directory = next(a for a in sn64.regions(image) if a['layout'] == 'sn64-sequences')
    assert directory['media'] == 'audio' and len(directory['samples']) == 1
    result = n64.preview(image, directory, {'sample': 0})
    assert result['details']['mixed_notes'] == 1
    assert result['details']['skipped_notes'] == 0
    with wave.open(io.BytesIO(base64.b64decode(result['data_url'].split(',')[1]))) as wav:
        assert any(wav.readframes(wav.getnframes()))


def test_non_music_sequences_remain_metadata():
    image = bytearray(music_fixture())
    directory = next(a for a in sn64.regions(image) if a['layout'] == 'sn64-sequences')
    struct.pack_into('>H', image, directory['sequences'][0]['offset'], 0)
    directory = next(a for a in sn64.regions(image) if a['layout'] == 'sn64-sequences')
    assert directory['media'] == 'metadata'
    assert 'samples' not in directory
