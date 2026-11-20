from array import array
from struct import pack
from types import SimpleNamespace

from decompassets.n64 import ead_render
from decompassets.n64.ead_font import Voice
from decompassets.n64.uso_audio import _Sample


def test_tempo_changes_preserve_elapsed_time():
    frame = ead_render._clock([(0, 120), (48, 90), (48, 60)])
    assert frame(48) == ead_render.RATE // 2
    assert frame(96) == round(ead_render.RATE * 1.5)


def test_looping_vadpcm_renders_a_panned_note_beyond_one_frame():
    image = bytes([0xc0, 0x77, 0x77, 0x77, 0x77, 0x77, 0x77, 0x77, 0x77])
    font = pack('>16h', *([0]*16))
    note = SimpleNamespace(tick=0, duration=4, key=39, program=0, velocity=127, volume=127, pan=0)
    sample = _Sample(0, len(image), 0, 1, loop=(0, 16))
    score = dict(notes=[note], tempos=[(0, 120)])
    pcm, stats = ead_render.render(image, score, [(note, Voice(0, 1.0), sample, font, 0)])
    samples = array('h')
    samples.frombytes(pcm)
    assert len(samples) == 2*round(ead_render.RATE/24)
    assert all(value == 0 for value in samples[1::2])
    assert any(samples[100::2])
    assert stats == dict(mixed_notes=1, unplayed_notes=0, truncated=False)
