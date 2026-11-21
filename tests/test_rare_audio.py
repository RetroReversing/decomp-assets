"""Synthetic inline ADPCM controls and a bounded sample table."""

import struct

from decompassets.n64 import audio, rare_audio


def test_inline_bank_validates_and_previews_adjacent_frames():
    instruments, voices = 16, 32
    controls = 8+18*instruments
    table = (controls+216*voices+15)&~15
    image = bytearray(table+20*voices)
    struct.pack_into('>4H',image,0,instruments,0,0,22050)
    for index in range(instruments):
        struct.pack_into('>HH',image,8+18*index+14,2,2*index)
    for index in range(voices):
        struct.pack_into('>II',image,controls+216*index+24,20*index,18)
    asset, = rare_audio.regions(image)
    assert len(asset['samples']) == voices
    assert audio.preview(image,asset,{'sample':31})['mime'] == 'audio/wav'
    image[table+20*31] = 4
    assert not rare_audio.regions(image)
