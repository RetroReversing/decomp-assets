import struct

from decompassets.n64.ead_font import Voice, voice


def test_instrument_ranges_and_tuning():
    data = bytearray(256)
    struct.pack_into('>I', data, 8, 32)
    data[33:35] = bytes((30, 50))
    struct.pack_into('>IfIfIf', data, 40, 80, 0.5, 96, 1.0, 112, 2.0)
    assert voice(data, (1, 0, 0), 0, 29) == Voice(80, 0.5)
    assert voice(data, (1, 0, 0), 0, 30) == Voice(96, 1.0)
    assert voice(data, (1, 0, 0), 0, 50) == Voice(96, 1.0)
    assert voice(data, (1, 0, 0), 0, 51) == Voice(112, 2.0)
    assert voice(data, (1, 0, 0), 1, 30) is None


def test_percussion_and_sound_effects_use_separate_tables():
    data = bytearray(128)
    struct.pack_into('>II', data, 0, 16, 48)
    struct.pack_into('>II', data, 16, 0, 24)
    data[25] = 80
    struct.pack_into('>If', data, 28, 64, 0.5)
    struct.pack_into('>If', data, 48, 80, 1.25)
    assert voice(data, (0, 2, 1), 127, 1) == Voice(64, 0.5, 80)
    assert voice(data, (0, 2, 1), 127, 0) is None
    assert voice(data, (0, 2, 1), 126, 0) == Voice(80, 1.25)
    assert voice(data, (0, 2, 1), 126, 1) is None
    struct.pack_into('>If', data, 48, 80, float('inf'))
    assert voice(data, (0, 2, 1), 126, 0) is None
    assert voice(data[:54], (0, 2, 1), 126, 0) is None
