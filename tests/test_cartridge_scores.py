"""Generated score directory, patch tables and distinct wave banks."""

import struct

from decompassets.n64 import audio, cartridge_scores, preview

from .test_native_audio import fixture, wav
from .test_paired_resources import _packed


def _image():
    single, _, sample_base = fixture(raw=True)
    control, waves = single[128:sample_base], single[sample_base:]
    wave_stride = (len(waves) + 15) & ~15
    controls = [4096 + i * len(control) for i in range(3)]
    wave_starts = [controls[-1] + len(control) + i * wave_stride for i in range(3)]
    image = bytearray(controls[0])
    struct.pack_into('>9I', image, 0, *controls, *controls[1:], wave_starts[0], *wave_starts)
    image.extend(control * 3)
    for i in range(3):
        samples = bytearray(waves)
        if i:
            samples[:32] = struct.pack('>16h', *([i * 3000, -1000] * 8))
        image.extend(samples.ljust(wave_stride, b'\0'))

    starts = []
    for bank in (0, 1, 0, 1):
        starts.append(len(image))
        # One track, normal and reused-duration notes, a rest, and an end.
        data = bytes([0, 2, 0xf0, bank, 0xd2, 0, 60, 10, 0, 0xff, 0xf2, 4, 0x68 + 62, 0xff, 0xff])
        score = _packed(data)
        image.extend(score.ljust((len(score) + 15) & ~15, b'\0'))
    struct.pack_into('>8I', image, 64, *starts, *starts[1:], len(image))
    struct.pack_into('>2I', image, 128, 0x80000100, 0x80000108)
    patch = bytes([0, 0, 127, 0, 0, 31, 64])
    for offset in (136, 144, 152):
        image[offset:offset + 7] = patch
    image[512:520] = bytes([1, 0, 1, 1, 1, 0, 1, 1])
    return image


def test_cartridge_score_uses_track_bounds_and_the_selected_instrument_bank():
    image = _image()
    asset, = cartridge_scores.regions(image, audio.regions(image))
    assert len(asset['samples']) == 4
    assert all(row['notes'] == 2 and row['preview_available'] for row in asset['samples'])
    first = preview(image, asset, {'sample': 0})
    second = preview(image, asset, {'sample': 1})
    assert first['details']['mixed_notes'] == second['details']['mixed_notes'] == 2
    assert wav(first)[1] != wav(second)[1]

    mismatched = bytearray(image)
    mismatched[512] = 2
    assert not cartridge_scores.regions(mismatched, audio.regions(mismatched))
    mismatched = bytearray(image)
    mismatched[83] += 1
    assert not cartridge_scores.regions(mismatched, audio.regions(mismatched))
