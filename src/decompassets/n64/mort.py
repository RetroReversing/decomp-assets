"""Bounded Factor 5 MORT speech decoding.

Based on the format behavior documented by SubDrag's public decoder research.
The bitstream uses little-endian bit order within big-endian 32-bit words.
"""

import struct

from ..formats import AssetError

HEADER = struct.Struct('>4sHHI')
SAMPLES_PER_FRAME = 160
_GAIN = (3277, 11469, 21299, 32767)
_WIDTHS = (6, 6, 5, 5, 4, 4, 3, 3)
_SCALES = (0x3333, 0x3333, 0x3333, 0x3333, 0x4b17, 0x4444, 0x7ade, 0x740c)
_BIASES = (0x4000, 0x4000, -0x332f000, 0x4003c00, -0x36e4e4, 0x3bbf800, 0x147936c, 0x40d6b40)


class _Bits:
    def __init__(self, data):
        self.words = iter(struct.iter_unpack('>I', data))
        self.buffer = self.available = 0

    def take(self, width):
        if self.available < width:
            word = next(self.words, None)
            if word is None:
                raise AssetError('The MORT frame data is truncated.')
            self.buffer |= word[0] << self.available
            self.available += 32
        value = self.buffer & ((1 << width) - 1)
        self.buffer >>= width
        self.available -= width
        return value


def _signed(value, width):
    midpoint = 1 << (width - 1)
    return ((value + midpoint) % (midpoint * 2)) - midpoint


def _q15(value):
    return _signed(value + 0x4000, 32) >> 15


def _reflection(value):
    magnitude = abs(value)
    if magnitude < 0x2b33:
        magnitude *= 2
    elif magnitude < 0x4e66:
        magnitude += 0x2b33
    else:
        magnitude = (magnitude >> 2) + 0x6600
    return min(magnitude, 32767) * (-1 if value < 0 else 1)


def _excitation(bits, history, lag):
    new_lag, gain, phase, scale = (bits.take(width) for width in (7, 2, 2, 6))
    if 40 <= new_lag <= 120:
        lag = new_lag
    exponent, mantissa = ((scale - 8) // 8, scale & 7) if scale >= 8 else (
        (-4, -3, -2, -2, -1, -1, -1, -1)[scale],
        (7, 7, 3, 7, 1, 3, 5, 7)[scale],
    )
    shift = 6 - exponent
    rounding = 1 << (shift - 1) if shift else 0
    excitation = [0] * 40
    for index in range(13):
        code = bits.take(3)
        scaled = ((code * 8192 - 28672) * (mantissa * 2048 + 18431) + 16384) >> 15
        excitation[phase + 3 * index] = _signed(_signed(scaled + rounding, 32) >> shift, 16)
    del history[:40]
    start = 120 - lag
    history.extend(_signed(_q15(history[start + i] * _GAIN[gain]) + value, 16)
                   for i, value in enumerate(excitation))
    return lag


def _synthesis(excitation, previous, current, delay, emphasis):
    bands = ((13, (2,), (1, 2)), (14, (1,), (1,)), (13, (1, 2), (2,)), (120, (0,), ()))
    start = 0
    output = []
    for length, new_shifts, old_shifts in bands:
        reflection = [_reflection(sum(new >> n for n in new_shifts) + sum(old >> n for n in old_shifts))
                      for old, new in zip(previous, current)]
        for sample in excitation[start:start + length]:
            sample = _signed(sample - _q15(delay[7] * reflection[7]), 32)
            for i in range(6, -1, -1):
                sample = _signed(sample - _q15(delay[i] * reflection[i]), 32)
                delay[i + 1] = _signed(delay[i] + _q15(sample * reflection[i]), 32)
            delay[0] = sample
            emphasis = _signed(sample + _q15(emphasis * 0x6e14), 32)
            output.append(max(-32768, min(32767, _signed(emphasis * 2, 32))) & ~7)
        start += length
    return output, _signed(emphasis, 16)


def decode(data, frame_limit):
    """Decode at most frame_limit frames to mono signed 16-bit little-endian PCM."""
    if len(data) < HEADER.size:
        raise AssetError('The MORT clip header is truncated.')
    magic, frames, rate, words = HEADER.unpack_from(data)
    if magic != b'MORT' or not frames or not 4000 <= rate <= 48000 or words * 4 != len(data):
        raise AssetError('The MORT clip header does not match its encoded extent.')
    bits = _Bits(memoryview(data)[HEADER.size:])
    history = [0] * 160
    lag = 40
    previous = [0] * 8
    delay = [0] * 8
    emphasis = voiced = silent = 0
    output = bytearray()
    for _ in range(min(frames, frame_limit)):
        if not voiced and not silent:
            if bits.take(1):
                silent = bits.take(4) + 1
            else:
                voiced = bits.take(7) + 1
        if silent:
            output.extend(bytes(SAMPLES_PER_FRAME * 2))
            silent -= 1
            continue
        voiced -= 1
        current = [_signed(((bits.take(width) - (1 << (width - 1))) * 1024 * scale + bias) >> 15 << 1, 16)
                   for width, scale, bias in zip(_WIDTHS, _SCALES, _BIASES)]
        for _ in range(4):
            lag = _excitation(bits, history, lag)
        samples, emphasis = _synthesis(history, previous, current, delay, emphasis)
        output.extend(struct.pack('<160h', *samples))
        previous = current
    return output
