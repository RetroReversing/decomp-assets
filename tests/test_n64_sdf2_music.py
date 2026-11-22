import base64
import io
import struct
import wave

from decompassets.n64 import sdf2_music


def _fixture():
    table = bytearray(160)
    struct.pack_into('>4sI4sI', table, 0, b'SDF2', len(table), b'BTEN', 2)
    # One instrument, one zone, followed by two timed songs.
    struct.pack_into('>I3I', table, 64, 1, 1, 112, 0)
    struct.pack_into('>I', table, 80, 2)
    struct.pack_into('>3I', table, 112, 124, 132, 0)
    table[124:132] = bytes((0, 127, 0, 127, 60, 0, 0, 0))
    image = table
    sample = b'\x60'+bytes([0x11]*8)
    for index in range(2):
        relative = len(image)
        struct.pack_into('>6I', image, 16+24*index, len(sample), 0, 16, relative, 22050, 0)
        image.extend(bytes(160)+sample)
    song = bytes.fromhex('00 ff 51 07 a1 20 00 c0 00 00 90 3c 64 08 ff 51 07 a1 20 08 3c 00 00 ff 2f')
    for index in range(2):
        struct.pack_into('>2I', image, 84+8*index, 120, len(image))
        image.extend(song)
    return bytes(image)


def test_song_directory_and_sample_backed_preview():
    image = _fixture()
    assets = sdf2_music.regions(image)
    assert len(assets) == 2
    result = sdf2_music.preview(image, assets[0], {'sample': 0})
    assert result['details']['mixed_notes'] == 1
    assert result['details']['skipped_notes'] == 0
    with wave.open(io.BytesIO(base64.b64decode(result['data_url'].split(',')[1]))) as stream:
        assert stream.getframerate() == 22050
        assert any(stream.readframes(stream.getnframes()))


def test_missing_song_end_is_rejected():
    image = _fixture()
    assert not sdf2_music.regions(image[:-1])
