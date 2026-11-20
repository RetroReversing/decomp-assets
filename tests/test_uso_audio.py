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
