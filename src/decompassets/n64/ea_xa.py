"""EA-XA mono frames in early big-endian sound banks.

Frame arithmetic: https://github.com/vgmstream/vgmstream/blob/master/src/coding/ea_xa_decoder.c
"""
import struct

from ..formats import AssetError

_COEFFICIENTS = (0, 240, 460, 392, 0, 0, -208, -220, 0, 1, 3, 4, 7, 8, 10, 11, 0, -1, -3, -4)


def decode(data, samples):
    """Expand complete 15-byte frames into little-endian signed PCM."""
    if samples < 0 or len(data) < ((samples + 27) // 28) * 15:
        raise AssetError('The EA-XA sample is incomplete. Scan ROM Explorer again.')
    output = []
    previous, older = 0, 0
    for at in range(0, ((samples + 27) // 28) * 15, 15):
        header = data[at]
        predictor, shift = header >> 4, (header & 15) + 8
        first, second = _COEFFICIENTS[predictor], _COEFFICIENTS[predictor + 4]
        for sample in range(28):
            value = (data[at + 1 + sample // 2] >> (4 if sample % 2 == 0 else 0)) & 15
            value = value if value < 8 else value - 16
            value = ((value << 28) >> shift) + first * previous + second * older + 128
            value = max(-32768, min(32767, value >> 8))
            output.append(value)
            older, previous = previous, value
    return struct.pack('<' + str(samples) + 'h', *output[:samples])
