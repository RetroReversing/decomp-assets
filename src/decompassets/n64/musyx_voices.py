"""Resolve N64 MusyX instrument pages to bounded sample starts."""

import struct

_KEY = struct.Struct('>Hbbb3x')
_LAYER = struct.Struct('>Hbbbbbbb3x')


def _signed(byte):
    return byte - 256 if byte >= 128 else byte


def _targets(image, pool, identifier, key):
    if identifier in pool['macro']:
        return [(identifier, key, 127, None)]
    if identifier in pool['keymap']:
        start, end = pool['keymap'][identifier]
        if end - start != 128 * _KEY.size:
            return ()
        macro, transpose, pan, _ = _KEY.unpack_from(image, start + key * _KEY.size)
        return [(macro, key + transpose, 127, pan)]
    if identifier in pool['layer']:
        start, end = pool['layer'][identifier]
        if end - start < 4:
            return ()
        count = int.from_bytes(image[start:start+4], 'big')
        if count > 128 or end - start != 4 + count * _LAYER.size:
            return ()
        return [(macro, key + shift, volume, pan)
                for macro, lo, hi, shift, volume, _, _, pan
                in _LAYER.iter_unpack(image[start+4:end]) if lo <= key <= hi]
    return ()


def _attack(image, macros, macro, key, velocity, modulation):
    """Run deterministic attack control flow up to the first sample start."""
    step = 0
    pitch = key
    for _ in range(128):
        if macro not in macros:
            return None
        start, end = macros[macro]
        offset = start + step * 8
        if offset + 8 > end:
            return None
        command = image[offset:offset+4][::-1] + image[offset+4:offset+8][::-1]
        op = command[0]
        step += 1
        if op in (0, 1):
            return None
        if op == 16:
            identifier, mode, offset = struct.unpack_from('<HBI', command, 1)
            if mode == 1:
                offset = offset * (127 - velocity) // 127
            elif mode == 2:
                offset = offset * velocity // 127
            return identifier, pitch, offset
        threshold = {2: key, 3: velocity, 10: modulation}.get(op, -1)
        if op == 6 or threshold >= command[1]:
            macro, step = struct.unpack_from('<HH', command, 2)
        elif op in (24, 25, 26):
            shift = _signed(command[1]) + _signed(command[2]) / 100
            pitch = shift if op == 25 else (key if op == 26 else pitch) + shift
        elif op in (5, 8, 19):
            # Branch choice requires delay, randomness or another voice.
            return None
    return None


def attacks(image, pool, identifier, key, velocity, modulation=0):
    """Return sample ID, pitch, start sample, layer volume and pan for each attack."""
    starts = []
    for macro, pitch_key, volume, pan in _targets(image, pool, identifier, key):
        if start := _attack(image, pool['macro'], macro, max(0, min(127, pitch_key)), velocity, modulation):
            starts.append((*start, volume, pan))
    return starts
