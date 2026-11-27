"""Decode mono DEAN transform audio with the codebooks kept in the ROM."""

import cmath
import math
import re
import struct
from functools import lru_cache
from itertools import islice

from ..formats import AssetError

BANDS = (4, 8, 12, 18, 25, 33, 44, 53, 63, 75, 89, 105, 126, 149, 185, 256)
BAND_SIGNATURE = struct.pack('>16H', *BANDS)
DESCRIPTOR = struct.Struct('>9i')
SECTION = struct.Struct('>5I')
NODE = struct.Struct('>HH')
BLOCK_SAMPLES = 128
SCALE_COUNT = 64
MAX_BLOCKS = 30 * 11025 // BLOCK_SAMPLES


def _tree(image, start, leaves):
    size = 2 * leaves - 1
    if not 0 <= start <= len(image) - size * NODE.size:
        return None
    nodes = tuple(NODE.iter_unpack(image[start:start + size * NODE.size]))
    pending = [0]
    visited = set()
    while pending:
        index = pending.pop()
        if index in visited or not 0 <= index < size:
            return None
        visited.add(index)
        left, right = nodes[index]
        if left != 0x800:
            pending.extend((left, right))
    return nodes if len(visited) == size else None


def _book(image, at, bias):
    low, high, _, escape_width, _, bin_count, phrase_count, phrase_ptr, tree_ptr = DESCRIPTOR.unpack_from(image, at)
    if (low, high) not in ((-127, 127), (-64, 64)) or escape_width != 16:
        return None
    if not 0 <= phrase_count <= 16 or bin_count != (256 if low == -127 else 129):
        return None
    leaves = high - low + 1 + (phrase_count + 2 if low == -127 else 0)
    nodes = _tree(image, (tree_ptr & 0xffffffff) - bias, leaves)
    if nodes is None:
        return None
    phrases = []
    phrase = (phrase_ptr & 0xffffffff) - bias
    for index in range(phrase_count):
        start = phrase + index * 0x1b8
        if not 0 <= start <= len(image) - 0x1b8:
            return None
        count, = struct.unpack_from('>I', image, start + 0x1a0)
        if not 1 <= count <= 64:
            return None
        phrases.append(tuple(struct.unpack_from('>h', image, start + 0xa2 + i * 4)[0] for i in range(count)))
    return nodes, tuple(phrases)


def _tables(image, anchor, *, linked_program=False):
    for padding in (24, 16, 8):
        if tables := _book_layout(image, anchor, padding, linked_program):
            return tables
    return None


def _book_layout(image, anchor, padding, linked_program):
    # The scale ladder is followed by a fixed bank of book descriptors and
    # four sections. The first section points back to the fourth descriptor.
    scale_at = anchor + len(BAND_SIGNATURE)
    descriptor = scale_at + SCALE_COUNT * 4 + padding
    section = descriptor + 4 * DESCRIPTOR.size + 4
    if section + 4 * SECTION.size > len(image):
        return None
    sections = list(SECTION.iter_unpack(image[section:section + 4 * SECTION.size]))
    if [(start, size) for _, start, size, _, _ in sections] != [(0, 16), (0, 35), (35, 89), (124, 132)]:
        return None
    bias = sections[0][-1] - (descriptor + 3 * DESCRIPTOR.size)
    if bias < (0 if linked_program else 0x70000000):
        return None
    books = []
    for index, (_, _, _, _, pointer) in enumerate(sections):
        expected = descriptor + ((index - 1) % 4) * DESCRIPTOR.size
        if pointer - bias != expected or not (book := _book(image, expected, bias)):
            return None
        books.append(book)
    scales = struct.unpack_from(f'>{SCALE_COUNT}f', image, scale_at)
    if any(not 0 < value <= 1 for value in scales):
        return None
    return scales, books


def table_offset(image, *, linked_program=False):
    for match in islice(re.finditer(re.escape(BAND_SIGNATURE), image), 32):
        at = match.start()
        if at % 4 == 0 and _tables(image, at, linked_program=linked_program):
            return at
    return None


class _Bits:
    def __init__(self, data):
        self.data = data
        self.cursor = self.word = self.remaining = 0
        self.branch = self.branch_remaining = 0

    def read(self, width):
        if self.remaining < width:
            if self.cursor + 2 > len(self.data):
                raise AssetError('The DEAN bitstream ends inside a frame.')
            self.word = (self.word << 16) | int.from_bytes(self.data[self.cursor:self.cursor + 2], 'big')
            self.cursor += 2
            self.remaining += 16
        self.remaining -= width
        value = self.word >> self.remaining
        self.word &= (1 << self.remaining) - 1
        return value

    def bit(self):
        if not self.branch_remaining:
            self.branch = self.read(16)
            self.branch_remaining = 16
        self.branch_remaining -= 1
        return (self.branch >> self.branch_remaining) & 1

    def literal(self):
        # Escape words use the remaining Huffman bits first, then replenish
        # the low part from the interleaved raw bitstream.
        extra = self.read(16)
        remaining = self.branch_remaining
        prefix = (self.branch & ((1 << remaining) - 1)) << (16 - remaining)
        self.branch = extra & ((1 << remaining) - 1)
        value = prefix | (extra >> remaining)
        return value - 65536 if value >= 32768 else value


def _coefficients(bits, books, initial, count):
    values = []
    section = initial
    end = 16 if initial == 0 else 35
    while len(values) < count:
        nodes, phrases = books[section]
        index = 0
        while nodes[index][0] != 0x800:
            index = nodes[index][bits.bit()]
        word = nodes[index][1]
        mode = word & 0xf00
        if mode in (0, 0xf00):
            values.append(word - 65536 if word >= 32768 else word)
        elif word == 0x900:
            values.append(bits.literal())
        elif mode == 0xa00 and (phrase := word & 255) < len(phrases):
            values.extend(phrases[phrase])
        elif mode == 0xb00:
            values.extend([0] * (count - len(values)))
        else:
            raise AssetError('The DEAN codebook contains an unsupported symbol.')
        if len(values) >= end and section in (1, 2):
            end += (89, 132)[section - 1]
            section += 1
    if len(values) != count:
        raise AssetError('A DEAN phrase overruns its frame.')
    return values


@lru_cache(maxsize=1)
def _transform_params():
    pre = tuple(cmath.exp(2j * math.pi * (4 * i + 1) / 2048) for i in range(128))
    angles = [2 * math.pi * i / 512 for i in range(128)]
    post = tuple(complex(math.cos(a) + math.sin(a), math.sin(a) - math.cos(a)) for a in angles)
    permutation = tuple(int(f'{i:07b}'[::-1], 2) for i in range(128))
    roots = tuple(cmath.exp(2j * math.pi * i / 128) for i in range(64))
    return pre, post, permutation, roots


def _synthesize(coeffs, previous):
    pre, post, permutation, roots = _transform_params()
    packed = [complex(coeffs[2*i], coeffs[255-2*i]) * pre[i] for i in range(128)]
    bins = [packed[i] for i in permutation]
    for width in (2, 4, 8, 16, 32, 64, 128):
        half = width // 2
        for start in range(0, 128, width):
            for index in range(half):
                left = start + index
                right = left + half
                term = roots[index * (128 // width)] * bins[right]
                bins[right] = bins[left] - term
                bins[left] += term
    pcm = []
    for index, (item, angle) in enumerate(zip(bins, post)):
        item *= angle
        sample = (previous[index] * pre[index].real + item.imag * pre[index].imag) * (32768 / math.sqrt(2))
        pcm.append(min(32767, max(-32768, int(sample + math.copysign(0.5, sample)))))
        previous[index] = item.real
    return pcm


def decode(image, anchor, payload, frames, *, linked_program=False):
    if not 1 <= frames <= MAX_BLOCKS:
        raise AssetError('The DEAN preview exceeds its frame limit.')
    tables = _tables(image, anchor, linked_program=linked_program) if isinstance(anchor, int) and 0 <= anchor < len(image) else None
    if tables is None:
        raise AssetError('The DEAN codebooks could not be verified. Rescan ROM Explorer.')
    scales, books = tables
    # The reader reserves the final complete word as an end-of-stream lookahead.
    bits = _Bits(payload[:max(0, len(payload) // 2 * 2 - 2)])
    gain = [bits.read(6) for _ in BANDS]
    previous = [0.0] * BLOCK_SAMPLES
    output = bytearray()
    for index in range(frames):
        if index:
            gain = [level + change for level, change in zip(gain, _coefficients(bits, books, 0, 16))]
        if any(not 0 <= level < len(scales) for level in gain):
            raise AssetError('A DEAN frame has an invalid scale index.')
        coeffs = _coefficients(bits, books, 1, 256)
        start = 0
        for end, level in zip(BANDS, gain):
            factor = 1 / (32768 * scales[level])
            coeffs[start:end] = [value * factor for value in coeffs[start:end]]
            start = end
        output.extend(struct.pack('<128h', *_synthesize(coeffs, previous)))
    return bytes(output)
