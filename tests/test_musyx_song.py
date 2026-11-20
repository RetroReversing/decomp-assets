import struct

from decompassets.n64 import musyx_song


def test_arrangement_and_revised_events_are_bounded():
    first_track = 280
    region_table = first_track + 24
    stream_start = region_table + 4
    channels = stream_start + 24
    song = (
        struct.pack('>6I', 24, region_table, channels, 0, 120, 0)
        + struct.pack('>64I', first_track, *([0] * 63))
        + struct.pack('>IBBHhh', 0, 255, 0, 0, 0, 0)
        + struct.pack('>IBBHhh', 96, 255, 0, 0, -2, 0)
        + struct.pack('>I3I', stream_start, 8, 0, 0)
        + struct.pack('>HBBHHBBH', 24, 60, 100, 72, 72, 255, 255, 0xdead)
        + bytes(64)
    )
    layout = musyx_song.arrangement(song)
    assert layout['tempo'] == 120
    assert layout['tracks'][0]['loop_to'] == 0
    assert layout['streams'] == [(stream_start, channels)]
    assert musyx_song.events(song, *layout['streams'][0]) == [
        {'tick': 24, 'kind': 'note', 'key': 60, 'value': 100, 'duration': 72}
    ]
    assert musyx_song.events(song, stream_start, channels-5) is None
    assert musyx_song.arrangement(song[:-1]) is None
