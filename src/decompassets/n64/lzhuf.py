"""Bounded adaptive-Huffman LZ decoding with a 4 KiB sliding window."""

from ..formats import AssetError

_NCHAR = 314
_T = 627
_ROOT = 626
_LIMIT = 4 * 1024 * 1024


def unpack(source, size, check=lambda: None, *, prefix=None, fill=32):
    if not 0 < size <= _LIMIT:
        raise AssetError('The Huffman output size is invalid.')
    freq = [0] * (_T + 1)
    parent = [0] * (_T + _NCHAR)
    child = [0] * _T
    for i in range(_NCHAR):
        freq[i], child[i], parent[i + _T] = 1, i + _T, i
    i = 0
    for j in range(_NCHAR, _T):
        freq[j] = freq[i] + freq[i + 1]
        child[j] = i
        parent[i] = parent[i + 1] = j
        i += 2
    freq[_T] = 0xffff
    parent[_ROOT] = 0

    def rebuild():
        j = 0
        for i in range(_T):
            if child[i] >= _T:
                freq[j], child[j] = (freq[i] + 1) // 2, child[i]
                j += 1
        i = 0
        for j in range(_NCHAR, _T):
            f = freq[i] + freq[i + 1]
            k = j - 1
            while f < freq[k]:
                k -= 1
            k += 1
            freq[k+1:j+1] = freq[k:j]
            child[k+1:j+1] = child[k:j]
            freq[k], child[k] = f, i
            i += 2
        for i in range(_T):
            k = child[i]
            parent[k] = i
            if k < _T:
                parent[k+1] = i

    def update(symbol):
        if freq[_ROOT] == 0x8000:
            rebuild()
        c = parent[symbol + _T]
        while True:
            freq[c] += 1
            k = freq[c]
            if k > freq[c + 1]:
                other = c + 1
                while k > freq[other + 1]:
                    other += 1
                freq[c], freq[other] = freq[other], k
                a, b = child[c], child[other]
                parent[a] = other
                if a < _T:
                    parent[a + 1] = other
                parent[b] = c
                if b < _T:
                    parent[b + 1] = c
                child[c], child[other] = b, a
                c = other
            c = parent[c]
            if c == 0:
                break

    position = 0
    def bits(n):
        nonlocal position
        if position + n > len(source) * 8:
            raise AssetError('The Huffman stream is truncated.')
        value = 0
        for _ in range(n):
            value = (value << 1) | ((source[position // 8] >> (7 - position % 8)) & 1)
            position += 1
        return value

    window = bytearray(bytes([fill]) * 4036 + bytes(60))
    cursor = 4036
    output = bytearray()
    target = min(size, prefix) if prefix is not None else size
    while len(output) < target:
        if len(output) % 4096 < 60:
            check()
        c = child[_ROOT]
        while c < _T:
            c = child[c + bits(1)]
        c -= _T
        update(c)
        if c < 256:
            values = [c]
        else:
            lead = bits(8)
            if lead < 32:
                upper, length = 0, 3
            elif lead < 80:
                upper, length = 1 + (lead - 32) // 16, 4
            elif lead < 144:
                upper, length = 4 + (lead - 80) // 8, 5
            elif lead < 192:
                upper, length = 12 + (lead - 144) // 4, 6
            elif lead < 240:
                upper, length = 24 + (lead - 192) // 2, 7
            else:
                upper, length = 48 + lead - 240, 8
            n = length - 2
            distance = (upper << 6) | (((lead << n) | bits(n)) & 63)
            start = (cursor - distance - 1) & 4095
            values = None
            count = c - 253
            if len(output) + count > size:
                raise AssetError('The Huffman output exceeds its declared size.')
        if values is not None:
            output.append(c)
            window[cursor] = c
            cursor = (cursor + 1) & 4095
        else:
            for i in range(count):
                value = window[(start + i) & 4095]
                output.append(value)
                window[cursor] = value
                cursor = (cursor + 1) & 4095
    return bytes(output[:target])
