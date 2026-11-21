"""Two synthetic relocated banks and an adjacent compact MIDI cue tree."""

import struct

from decompassets.n64 import paired_audio, preview

from .test_compact_midi import _sequence
from .test_native_audio import fixture, wav
from .test_native_textures import indexed_set


def _relocate(control, address, sample_offset):
    copy = bytearray(control)
    for field in (4,44,80,84,128,132,136,144,148,152,272,296):
        value, = struct.unpack_from('>I', copy, field)
        struct.pack_into('>I', copy, field, address+value)
    for flag in (34,67,142,158,265,289):
        copy[flag] = 1
    for at in (256,280):
        value, = struct.unpack_from('>I', copy, at)
        struct.pack_into('>I', copy, at, sample_offset+value)
    return copy


def cartridge():
    image, _, base = fixture()
    control = image[128:base]
    virtual = 0x200000
    first = virtual+20
    second = first+len(control)
    split = 64
    music = _relocate(control, first, 0)
    effects = _relocate(control, second, split)
    table = image[base:base+58]
    song = bytearray(_sequence(bytes.fromhex('00 90 3c 60 81 00 00 ff 2f')))
    struct.pack_into('>I', song, 64, 3072)
    cue_keys = struct.pack('>4I', 4, 1, 5, 0)
    cues = indexed_set([cue_keys, indexed_set([bytes(8), song])])
    effects_index = indexed_set([indexed_set([])]*6)
    tree = indexed_set([effects_index, cues])
    directory = struct.pack('>5I', 2, first, 0, second, split)
    return directory+music+effects+table+bytes(6)+table+bytes(2)+tree


def test_relocated_banks_and_high_division_cue_play_through_the_n64_dispatch():
    image = cartridge()
    music, effects, cues = paired_audio.regions(image)
    assert music['table_offset'] == effects['table_offset']
    assert len(music['samples']) == len(effects['samples']) == 2
    assert wav(preview(image, effects, {'sample': 1}))[0] == 22050
    assert len(cues['samples']) == 1
    result = preview(image, cues, {})
    assert result['details']['mixed_notes'] == 1
    assert any(wav(result)[1])


def test_bad_split_table_frame_and_truncated_cue_tree_are_rejected():
    original = cartridge()
    bad = bytearray(original)
    bad[19] ^= 4
    assert not paired_audio.regions(bad)
    music = paired_audio.regions(original)[0]
    bad = bytearray(original)
    bad[music['table_offset']] = 0x01
    assert not paired_audio.regions(bad)
    assert not paired_audio.regions(original[:-1])
