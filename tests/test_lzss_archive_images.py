"""The image directory and each compressed stream must be bounded."""

import struct

from decompassets.n64 import lzss_archive_images, lzss_boot


def _literal(data):
    assert len(data) % 8 == 0
    return b''.join(b'\xff' + data[i:i+8] for i in range(0, len(data), 8))


def test_ring_stream_and_archive_previews():
    assert lzss_boot.decode(bytes([7]) + b'ABC' + bytes([0xee, 0xf3]), 9) == b'ABCABCABC'
    assert lzss_boot.decode(bytes([7]) + b'ABC' + bytes([0xee, 0xf3]), 8) is None
    payloads = [bytes([i]) * n for i, n in enumerate((4096, 512, 4096, 512))]
    streams = [_literal(p) for p in payloads]
    image = bytearray(8 + 16 * len(streams))
    struct.pack_into('>2I', image, 0, len(streams), 0)
    for i, (payload, stream) in enumerate(zip(payloads, streams)):
        struct.pack_into('>I4sII', image, 8 + 16 * i, len(image), b'LZSS', len(payload), len(stream))
        image.extend(stream)
    rows = lzss_archive_images.regions(image)
    assert len(rows) == 2
    assert lzss_archive_images.preview(image, rows[0], {})['details']['width'] == 64
    image[12:16] = b'BAD!'
    assert not lzss_archive_images.regions(image)
