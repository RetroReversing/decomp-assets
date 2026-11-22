"""Bounded adaptive-Huffman LZ stream used by some N64 IWAD members.

The format follows the published decoder in the wadutil64 project (GPL-3.0):
https://github.com/thekovic/wadutil64/blob/master/decodes.cpp
"""

_LIMIT = 4 * 1024 * 1024
_SHIFTS = (4, 6, 8, 10, 12, 14)
_LEAVES = 0x275


class _Decoder:
    def __init__(self, source):
        self.source = source
        self.at = self.bits = self.value = 0
        self.even = [0] * _LEAVES
        self.odd = [0] * _LEAVES
        self.parent = [0] * 1258
        self.weight = [0] * 1258
        for i in range(2, 1258):
            self.parent[i] = i // 2
            self.weight[i] = 1
        for i in range(1, _LEAVES):
            self.even[i], self.odd[i] = i * 2, i * 2 + 1

    def bit(self):
        if not self.bits:
            if self.at >= len(self.source):
                raise ValueError
            self.value = self.source[self.at]
            self.at += 1
            self.bits = 8
        result = bool(self.value & 128)
        self.value = (self.value << 1) & 255
        self.bits -= 1
        return result

    def _fix(self, a, b):
        while True:
            parent = self.parent[a]
            self.weight[parent] = self.weight[a] + self.weight[b]
            if parent == 1:
                break
            grand = self.parent[parent]
            b = self.odd[grand] if self.even[grand] == parent else self.even[grand]
            a = parent
        if self.weight[1] == 2000:
            self.weight = [value >> 1 for value in self.weight]

    def symbol(self):
        node = 1
        while node < _LEAVES:
            node = self.odd[node] if self.bit() else self.even[node]
        value = node - _LEAVES
        self.weight[node] += 1
        parent = self.parent[node]
        if parent != 1:
            sibling = self.odd[parent] if self.even[parent] == node else self.even[parent]
            self._fix(node, sibling)
            while parent != 1:
                grand = self.parent[parent]
                uncle = self.odd[grand] if self.even[grand] == parent else self.even[grand]
                if self.weight[uncle] < self.weight[node]:
                    if self.even[grand] == parent:
                        self.odd[grand] = node
                    else:
                        self.even[grand] = node
                    if self.even[parent] == node:
                        other = self.odd[parent]
                        self.even[parent] = uncle
                    else:
                        other = self.even[parent]
                        self.odd[parent] = uncle
                    self.parent[uncle] = parent
                    self.parent[node] = grand
                    self._fix(uncle, other)
                    node = uncle
                node = self.parent[node]
                parent = self.parent[node]
        return value


def unpack(source, expected, check=lambda: None):
    """Decode exactly the declared number of bytes, with a required end symbol."""
    if not 0 < expected <= _LIMIT:
        return None
    decoder = _Decoder(source)
    result = bytearray()
    bases = [0]
    for shift in _SHIFTS:
        bases.append(bases[-1] + (1 << shift))
    try:
        while len(result) <= expected:
            if len(result) % 4096 == 0:
                check()
            symbol = decoder.symbol()
            if symbol == 256:
                return bytes(result) if len(result) == expected else None
            if symbol < 256:
                result.append(symbol)
                continue
            group, length_code = divmod(symbol - 257, 62)
            if group >= len(_SHIFTS):
                return None
            count = length_code + 3
            extra = sum(int(decoder.bit()) << i for i in range(_SHIFTS[group]))
            distance = bases[group] + extra + count
            if distance > len(result) or len(result) + count > expected:
                return None
            for _ in range(count):
                result.append(result[-distance])
    except (ValueError, IndexError):
        return None
    return None
