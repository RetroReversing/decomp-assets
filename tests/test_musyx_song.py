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


def test_render_uses_assigned_sample_and_stereo_channel_controls():
    from decompassets.n64 import musyx, musyx_render, musyx_voices

    first_track, region_table, stream, channels = 280, 304, 308, 332
    song = (
        struct.pack('>6I', 24, region_table, channels, 0, 120, 0)
        + struct.pack('>64I', first_track, *([0] * 63))
        + struct.pack('>IBBHhh', 0, 255, 0, 0, 0, 0)
        + struct.pack('>IBBHhh', 96, 255, 0, 0, -1, 0)
        + struct.pack('>I3I', stream, 8, 0, 0)
        + struct.pack('>HBBHHBBH', 0, 60, 100, 72, 72, 255, 255, 0)
        + bytes(64)
    )
    start_sample = bytes.fromhex('0000071000000000')
    encoded = musyx.BOOK.pack(*([0] * 128)) + struct.pack('>4h', 10000, 10000, 10000, 10000) + bytes(32)
    image = start_sample + encoded
    pool = {'macro': {1: (0, 8)}, 'keymap': {}, 'layer': {}}
    assert musyx_voices.attacks(image, pool, 1, 60, 100) == [(7, 60, 0, 127, None)]
    group = {'pages': {0: {'object_id': 1}}, 'drums': {}, 'setups': {0: [(0, 127, 0, 0, 0)] * 16}}
    sample = dict(preview_available=True, samples=64, offset=8, rate=22050, root_key=60, loop_start=0, loop_end=0)
    pcm, details = musyx_render.render(image, song, group, 0, pool, {7: sample})
    assert details['mixed_notes'] == 1 and details['skipped_notes'] == 0
    left, right = struct.unpack_from('<hh', pcm)
    assert left > 0 and right == 0
