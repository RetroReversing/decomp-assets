"""Look up EAD instrument, drum and sound-effect samples in a sound font."""

import math
import struct
from dataclasses import dataclass

_POINTER = struct.Struct('>I')
_TUNED_SAMPLE = struct.Struct('>If')


@dataclass(frozen=True)
class Voice:
    descriptor: int
    tuning: float
    pan: int | None = None


def _pointer(data, at, size):
    if 0 <= at <= len(data)-_POINTER.size:
        target, = _POINTER.unpack_from(data, at)
        if 0 < target <= len(data)-size and target % 4 == 0:
            return target
    return None


def voice(data, counts, program, key):
    """Resolve a note to a font-local sample descriptor and its tuning."""
    instruments, drums, effects = counts
    pan = None
    if program == 127:
        if not 0 <= key < drums:
            return None
        table = _pointer(data, 0, drums*4)
        drum = _pointer(data, table+key*4, 16) if table is not None else None
        if drum is None:
            return None
        at, pan = drum+4, data[drum+1]
    elif program == 126:
        if not 0 <= key < effects:
            return None
        table = _pointer(data, 4, effects*8)
        if table is None:
            return None
        at = table+key*8
    else:
        if not 0 <= program < instruments or not 0 <= key <= 127:
            return None
        instrument = _pointer(data, 8+program*4, 32)
        if instrument is None:
            return None
        low, high = data[instrument+1:instrument+3]
        if low > high:
            return None
        at = instrument+(8 if key < low else 24 if key > high else 16)
    descriptor = _pointer(data, at, 16)
    if descriptor is None:
        return None
    _, tuning = _TUNED_SAMPLE.unpack_from(data, at)
    if not math.isfinite(tuning) or tuning <= 0:
        return None
    return Voice(descriptor, tuning, pan)
