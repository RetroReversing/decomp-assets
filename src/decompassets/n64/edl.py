"""Eurocom EDL streams. See https://dsll32.github.io/nviewer/wiki/compression/edl.html."""

import struct

from ..formats import AssetError

HEADER = 12
LIMIT = 4 * 1024 * 1024


def header(image, offset):
    if offset < 0 or offset + HEADER > len(image) or image[offset:offset + 3] != b'EDL':
        return None
    flags = image[offset + 3]
    method = flags & 127
    stored, size = struct.unpack_from('>II' if flags & 128 else '<II', image, offset + 4)
    if (method > 2 or not HEADER <= stored <= min(LIMIT, len(image) - offset)
            or not 0 < size <= LIMIT or (stored % 4 if method else stored != HEADER + size)):
        return None
    return method, stored, size, bool(flags & 128)


class Bits:
    def __init__(self, source, big_endian):
        self.words = iter(struct.iter_unpack('>I' if big_endian else '<I', source))
        self.value = self.remaining = 0

    def read(self, width):
        if self.remaining < width:
            word = next(self.words, None)
            if word is None:
                raise AssetError('The EDL bitstream is truncated.')
            self.value |= word[0] << self.remaining
            self.remaining += 32
        result = self.value & ((1 << width) - 1)
        self.value >>= width
        self.remaining -= width
        return result


def _distance(read):
    high = 0
    if read(1):
        a, b = read(1), read(1)
        if not b:
            high = 1 if a else 2 + read(1)
        else:
            high = 4 + 2 * a + read(1)
            if not read(1):
                high = 2 * high + read(1)
    return 1 + high * 256 + read(8)


def _fixed(read, literal, copy):
    while True:
        if not read(1):
            literal(read(8))
        elif not read(1):
            length = 4 + read(1)
            if read(1):
                length = 2 * (length - 1) + read(1)
            if length == 9:
                for _ in range(12 + 4 * read(4)):
                    literal(read(8))
            else:
                copy(_distance(read), length)
        elif not read(1):
            copy(1 + read(8), 2)
        elif not read(1):
            copy(_distance(read), 3)
        else:
            length = read(8)
            if not length:
                return
            copy(_distance(read), 8 + length)


def _symbol(read, codes):
    code = 0
    for width in range(1, 16):
        code = (code << 1) | read(1)
        symbol = codes.get((width, code))
        if symbol is not None:
            return symbol
    raise AssetError('Invalid EDL Huffman code.')


def _table(read, previous, width):
    count = read(9)
    if not count:
        return previous, width
    lengths = []
    for symbol in range(count):
        if read(1):
            width = read(4)
        if width:
            lengths.append((width, symbol))
    codes = {}
    code = old_width = 0
    for length, symbol in sorted(lengths):
        code <<= length - old_width
        if code >= 1 << length:
            raise AssetError('Oversubscribed EDL Huffman table.')
        codes[length, code] = symbol
        old_width = length
        code += 1
    return codes, width


def _huffman(read, literal, copy):
    lengths, distances, width = {}, {}, 0
    while True:
        if read(1):
            lengths, width = _table(read, lengths, width)
            distances, width = _table(read, distances, width)
            while (symbol := _symbol(read, lengths)) != 256:
                if symbol < 256:
                    literal(symbol)
                    continue
                code = symbol - 257
                if code > 28:
                    raise AssetError('Invalid EDL match length.')
                if code < 8:
                    length = 3 + code
                elif code == 28:
                    length = 258
                else:
                    extra = (code >> 2) - 1
                    length = 3 + ((4 + (code & 3)) << extra) + read(extra)
                code = _symbol(read, distances)
                if code >= 30:
                    raise AssetError('Invalid EDL match distance.')
                if code < 4:
                    distance = code + 1
                else:
                    extra = (code >> 1) - 1
                    distance = 1 + ((2 + (code & 1)) << extra) + read(extra)
                copy(distance, length)
        else:
            for _ in range(read(15)):
                literal(read(8))
        if read(1):
            return


def unpack(image, offset=0):
    info = header(image, offset)
    if info is None:
        raise AssetError('The EDL header or extent is invalid.')
    method, stored, size, big_endian = info
    source = image[offset + HEADER:offset + stored]
    if not method:
        return source

    output = bytearray()

    def literal(value):
        if len(output) == size:
            raise AssetError('EDL output exceeds the declared size.')
        output.append(value)

    def copy(distance, count):
        if distance > len(output) or len(output) + count > size:
            raise AssetError('EDL match exceeds its input or output bounds.')
        pattern = output[-distance:]
        if count <= distance:
            output.extend(pattern[:count])
        else:
            output.extend((pattern * ((count + distance - 1) // distance))[:count])

    bits = Bits(source, big_endian)
    (_huffman if method == 1 else _fixed)(bits.read, literal, copy)
    if len(output) != size or next(bits.words, None) is not None:
        raise AssetError('EDL stream does not match its declared extents.')
    return bytes(output)
