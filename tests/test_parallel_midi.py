"""Validate all sequence extents in mirrored ROM offset arrays."""

import struct

from decompassets.n64 import parallel_midi


def _image():
    image = bytearray(0x282)
    struct.pack_into('>6I', image, 16, 0x100, 0x180, 0x200, 0x180, 0x200, 0x280)
    for start in (0x100, 0x180, 0x200):
        struct.pack_into('>I60xI', image, start, 68, 480)
        score = bytes.fromhex('00 90 3c 64 08 08 ff 2f')
        image[start + 68:start + 68 + len(score)] = score
    image[0x280:] = b'B1'
    return image


def test_parallel_arrays_validate_three_bounded_scores():
    rows, events = parallel_midi._rows(_image(), 16, 0x100, lambda: None)
    assert [row['offset'] for row in rows] == [0x100, 0x180, 0x200]
    assert all(row['notes'] == 1 for row in rows)
    assert len(events) == 3


def test_reject_nonmatching_end_array_and_invalid_track():
    image = _image()
    image[31] -= 1
    assert parallel_midi._rows(image, 16, 0x100, lambda: None) == ([], [])
    image = _image()
    image[0x180 + 69] = 0xf0
    assert parallel_midi._rows(image, 16, 0x100, lambda: None) == ([], [])
