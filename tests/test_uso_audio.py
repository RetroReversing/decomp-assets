import struct
from types import SimpleNamespace

from decompassets.n64 import uso_audio


def test_uso_wave_base_requires_every_selector_and_unique_placement():
    frames = (bytes([0x21]) + b'\xff'*8) * 10
    region = frames + b'\xff'*6
    table = region * 3
    samples = [uso_audio._Sample(i*96, 90, 0, 2) for i in range(3)]
    leading = b'\xff'*16
    assert uso_audio._wave_base(leading + table, samples, lambda: None) == 16
    assert uso_audio._wave_base(leading + table * 2, samples, lambda: None) is None
    broken = bytearray(leading + table)
    broken[16+96*2+9*9] = 0x22
    assert uso_audio._wave_base(broken, samples, lambda: None) is None


def test_sequence_voice_can_share_a_nonadjacent_predictor_book():

    data = bytearray(144)
    struct.pack_into('>I', data, 8, 16)
    data[18] = 127
    struct.pack_into('>If', data, 32, 48, 1.0)
    struct.pack_into('>4I', data, 48, 0x30000005, 0, 64, 96)
    struct.pack_into('>3I', data, 64, 0, 16, 0)
    struct.pack_into('>2I', data, 96, 2, 1)
    directory = dict(fonts=[(0, len(data), 2, 0, 0, 255, 1, 0, 0, 0)],
                     waves=[(0, 5)])
    note = SimpleNamespace(font=None, program=0, key=39)
    (matched, voice, sample, font, wave), = uso_audio.sequence_voices(
        bytes(data)+bytes(5), 0, len(data), directory, [0], [note])
    assert matched is note and font == data and wave == len(data)
    assert voice.tuning == 1 and sample.frame_size == 5 and sample.book == 104
