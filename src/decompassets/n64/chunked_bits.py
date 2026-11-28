"""Bounded MSB-first literal and backreference streams in resource directories."""

_LIMIT = 4 * 1024 * 1024


class _Truncated(Exception):
    pass


class _Bits:
    def __init__(self, data, offset):
        self.data, self.at = data, offset * 8

    def read(self, count):
        if self.at + count > len(self.data) * 8:
            raise _Truncated
        result = 0
        for _ in range(count):
            result = result * 2 + ((self.data[self.at // 8] >> (7 - self.at % 8)) & 1)
            self.at += 1
        return result


def decode(source, expected):
    """Decode literals and bounded backward copies across 4 KiB input pages."""
    if not 0 < expected <= _LIMIT or not 6 <= len(source) <= _LIMIT or source[:5] != b'\x03\0\0\x10\0':
        return None
    out = bytearray()
    horizon, width = 2, 1
    try:
        for chunk in range(0, len(source), 4096):
            bits = _Bits(source[chunk:chunk + 4096], 5 if not chunk else 0)
            while len(bits.data) * 8 - bits.at >= 8 and len(out) < expected:
                if bits.read(1):
                    length = bits.read(7)
                    if len(out) + length > expected:
                        return None
                    out.extend(bits.read(8) for _ in range(length))
                    continue
                prefix = 0
                while prefix < 7 and not bits.read(1):
                    prefix += 1
                length = ((1 << prefix) | bits.read(prefix)) if prefix else 1
                length += 2
                if len(out) + length > expected or not out:
                    return None
                while len(out) >= horizon:
                    if horizon < 65536:
                        width += 1
                    horizon *= 2
                threshold = (1 << width) - 1 - min(len(out), 65536)
                if threshold == -1:
                    distance = bits.read(width)
                else:
                    distance = bits.read(width - 1)
                    if distance >= threshold:
                        distance = distance * 2 + bits.read(1) - threshold
                begin = len(out) - distance
                if not 0 <= begin < len(out):
                    return None
                for _ in range(length):
                    out.append(out[begin])
                    begin += 1
    except _Truncated:
        return None
    return bytes(out) if len(out) == expected else None

