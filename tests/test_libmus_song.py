import struct

from decompassets.n64 import libmus_song


def test_raw_music_tracks_are_bounded_and_resolve_waves():
    first = bytes.fromhex('95 ff 81 01 85 78 30 18 96')
    second = bytes.fromhex('81 01 32 18 80')
    song = struct.pack('>12I', 2,24,32,40,48,48,48,48+len(first),0,0,0,0)+first+second
    score = libmus_song.song(song, {1})
    assert score['extent'] == len(song)
    assert score['loops'] == 1 and score['tempos'] == [(0,120)]
    assert [(note.key, note.wave, note.duration) for note in score['notes']] == [(48,1,24),(50,1,24)]
    assert libmus_song.song(song, {2}) is None
    assert libmus_song.song(song[:-1], {1}) is None


def test_archive_selects_two_songs_against_their_sample_bank():
    from decompassets.n64 import lzari, ptr_audio

    from .test_ptr_audio import _PACKED_SONG, fixture, wav
    from .test_raw_deflate_lists import _archive_image

    score, _ = lzari.unpack(_PACKED_SONG, order='big')
    padded = score.ljust((len(score) + 15) & ~15, b'\0')
    archive = struct.pack('>2sHII', b'\xaa\xa5', 2, 16, 16 + len(padded)) + bytes(4) + padded * 2
    image = bytearray(fixture())
    image.extend(bytes(-len(image) % 16))
    directory = len(image)
    image.extend(bytes(64))
    image = _archive_image(archive, image, directory)
    banks = ptr_audio.regions(image)
    assets = [asset for asset in libmus_song.regions(image, banks)
              if asset.get('sequence_codec') == 'raw-deflate-directory']
    assert len(assets) == 4 and len(assets[0]['samples']) == 2
    assert any(wav(libmus_song.preview(image, assets[0], {'sample': 1}))[2])
    assert not libmus_song.regions(image, [])


def test_original_pointer_song_validates_channel_tracks():
    first = bytes.fromhex('95 ff 81 01 85 78 30 18 96')
    second = bytes.fromhex('81 01 32 18 80')
    data = bytearray(160)
    struct.pack_into('>4I', data, 0, 16, 80, 148, 144)
    struct.pack_into('>2I', data, 16, 160, 160 + len(first))
    data.extend(first + second)
    score = libmus_song.v1_song(data, {1})
    assert score['channels'] == 2 and score['loops'] == 1
    assert [(note.key, note.wave) for note in score['notes']] == [(48, 1), (50, 1)]
    assert libmus_song.v1_song(data, {2}) is None
    assert libmus_song.v1_song(data[:-1], {1}) is None
