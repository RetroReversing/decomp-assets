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
