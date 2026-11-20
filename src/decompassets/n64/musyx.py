"""Decode the paired 32-sample frames used by N64 MusyX."""

import struct

from ..formats import AssetError

BOOK = struct.Struct('>128h')
PAIR_BYTES = 40
PAIR_SAMPLES = 64


def byte_length(samples):
    return BOOK.size + (samples + PAIR_SAMPLES - 1) // PAIR_SAMPLES * PAIR_BYTES


def decode(image, offset, samples):
    """Return signed 16-bit little-endian PCM using the sample's own predictor book.

    Frame layout and fixed-point arithmetic are documented by mupen64plus-rsp-hle,
    src/musyx.c and src/audio.c. Each half starts from its two stored PCM samples.
    """
    end = offset + byte_length(samples)
    if offset < 0 or samples <= 0 or end > len(image):
        raise AssetError('The MusyX sample is truncated.')
    coefficients = BOOK.unpack_from(image, offset)
    output = []
    for pair in range(offset + BOOK.size, end, PAIR_BYTES):
        for half in range(2):
            if len(output) >= samples:
                break
            start = pair + 8 + half * 16
            header = image[start]
            predictor = header >> 4
            if predictor >= 8:
                raise AssetError('The MusyX sample references a missing predictor.')
            shift = header & 15
            book = coefficients[predictor * 16:predictor * 16 + 16]
            frame = list(struct.unpack_from('>2h', image, pair + half * 4))
            residuals = [(nibble if nibble < 8 else nibble - 16) * 4096 >> shift
                         for byte in image[start + 1:start + 16] for nibble in (byte >> 4, byte & 15)]
            for first, count in ((0, 6), (6, 8), (14, 8), (22, 8)):
                older, newer = frame[-2:]
                group = residuals[first:first + count]
                for index, residual in enumerate(group):
                    correction = sum(book[8 + j] * group[index - 1 - j] for j in range(index))
                    value = ((residual << 11) + book[index] * older + book[8 + index] * newer + correction) >> 11
                    frame.append(max(-32768, min(32767, value)))
            output.extend(frame)
    return struct.pack(f'<{samples}h', *output[:samples])
