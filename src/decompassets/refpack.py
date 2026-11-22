"""Bounded RefPack streams with a three-byte expanded-size header.

Command encodings: https://github.com/OpenReliant/openreliant/blob/main/docs/formats/refpack.md
"""

from .formats import MAX_BYTES, AssetError


def unpack(source):
    """Return expanded bytes and consumed input, rejecting truncated or unsafe matches."""
    if len(source) < 5 or source[:2] != b'\x10\xfb':
        raise AssetError('This is not a supported RefPack stream.')
    expected = int.from_bytes(source[2:5], 'big')
    if not 0 < expected <= MAX_BYTES:
        raise AssetError('The RefPack output size is invalid.')
    at, output = 5, bytearray()
    try:
        while True:
            command = source[at]
            at += 1
            distance = length = 0
            if command < 0x80:
                b = source[at]
                at += 1
                literal, length = command & 3, ((command >> 2) & 7) + 3
                distance = ((command & 0x60) << 3) + b + 1
            elif command < 0xc0:
                b, c = source[at], source[at+1]
                at += 2
                literal, length = b >> 6, (command & 63) + 4
                distance = ((b & 63) << 8) + c + 1
            elif command < 0xe0:
                b, c, d = source[at], source[at+1], source[at+2]
                at += 3
                literal, length = command & 3, ((command & 12) << 6) + d + 5
                distance = ((command & 16) << 12) + (b << 8) + c + 1
            elif command < 0xfc:
                literal = ((command & 31) << 2) + 4
            else:
                literal = command & 3
            if at + literal > len(source) or len(output) + literal + length > expected:
                raise AssetError('The RefPack stream is truncated or exceeds its declared size.')
            output.extend(source[at:at+literal])
            at += literal
            if length and distance > len(output):
                raise AssetError('The RefPack stream has an invalid back-reference.')
            for _ in range(length):
                output.append(output[-distance])
            if command >= 0xfc:
                if len(output) != expected:
                    raise AssetError('The RefPack output does not match its declared size.')
                return bytes(output), at
    except IndexError:
        raise AssetError('The RefPack stream is truncated.') from None
