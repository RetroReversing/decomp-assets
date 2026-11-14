"""VPK0, the Huffman-coded LZ packing a fighting game's files use, unpacked as its own decoder does.

The stream is "vpk0", the unpacked size (32 bits), a sample method (8 bits), then a bit stream read most
significant bit first: two Huffman trees (bit 0 then eight bits: a leaf; bit 1: join the two nodes on top of the
stack, or end the tree when fewer than two are there), whose leaves are bit counts for back-reference distances
and lengths, then the data: bit 0 then eight bits is a literal byte, bit 1 a back-reference. With method 1 a
distance is read in two samples: a value of 0-2 adds 1-3 bytes to a distance read again, counted in words.
"""
from __future__ import annotations

from ..formats import AssetError

MAX_OUTPUT = 4 * 1024 * 1024
MAX_NODES = 64


class _Bits:
    """Bits most significant first, refilled four bytes at a time."""

    def __init__(self, data):
        self.data, self.at, self.acc, self.n = data, 0, 0, 0

    def read(self, n):
        while self.n < n:
            chunk = self.data[self.at:self.at+4]
            if not chunk:raise AssetError('The VPK0 stream ends early. Rescan the ROM.')
            self.acc = (self.acc << 8*len(chunk)) | int.from_bytes(chunk, 'big')
            self.n += 8*len(chunk);self.at += 4
        self.n -= n
        value = self.acc >> self.n
        self.acc &= (1 << self.n) - 1
        return value


def _tree(bits):
    """A Huffman tree as nested (left, right) tuples with int leaves (bit counts)."""
    stack, nodes = [], 0
    while True:
        if bits.read(1):
            if len(stack) < 2:break
            right = stack.pop();stack[-1] = (stack[-1], right)
        else:stack.append(bits.read(8))
        nodes += 1
        if nodes > MAX_NODES:raise AssetError('The VPK0 stream\'s code tree is not valid here.')
    if not stack:raise AssetError('The VPK0 stream has an empty code tree.')
    return stack[0]


def _value(bits, tree):
    while isinstance(tree, tuple):tree = tree[bits.read(1)]
    return bits.read(tree)


def size(data):
    """The unpacked size a VPK0 header gives, or None when `data` doesn't start with one."""
    return int.from_bytes(data[4:8], 'big') if data[:4] == b'vpk0' and len(data) >= 9 else None


def unpack(data, limit=MAX_OUTPUT):
    total = size(data)
    if total is None or not 0 < total <= limit:raise AssetError('No VPK0 stream starts here, or it unpacks beyond the limit.')
    method = data[8]
    bits = _Bits(bytes(data[9:]))
    offsets, lengths = _tree(bits), _tree(bits)
    out = bytearray()
    while len(out) < total:
        if not bits.read(1):
            out.append(bits.read(8));continue
        if method:
            value, extra = _value(bits, offsets), 0
            if value <= 2:extra, value = value + 1, _value(bits, offsets)
            start = len(out) - value*4 - extra + 8
        else:start = len(out) - _value(bits, offsets)
        length = _value(bits, lengths)
        if start < 0 or start >= len(out) and length:raise AssetError('The VPK0 stream refers back before its start.')
        if start + length <= len(out):out += out[start:start+length]
        else:
            for k in range(length):out.append(out[start + k])
    return bytes(out[:total])
