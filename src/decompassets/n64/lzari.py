"""Bounded LZARI decoding for size-prefixed Nintendo 64 control data.

Format reference: https://github.com/jombo23/N64-Tools/blob/master/N64SoundListToolUpdated/N64SoundLibrary/n643docompression.cpp
"""


class LzariError(ValueError):
    pass


def unpack(data, *, order='big', limit=1<<20, check=lambda: None):
    size = int.from_bytes(data[:4], order)
    if not 0 < size <= limit or len(data) < 7:
        raise LzariError('Invalid arithmetic stream size.')
    symbols = [0, *range(314)]
    counts = [0]+[1]*314
    cumulative = list(range(314, -1, -1))
    distance = [0]*4097
    for i in range(4096, 0, -1):
        distance[i-1] = distance[i]+10000//(i+200)
    position = 32
    def bit():
        nonlocal position
        if position >= len(data)*8:
            raise LzariError('Truncated arithmetic stream.')
        value = (data[position//8] >> (7-position%8)) & 1
        position += 1
        return value
    code = 0
    for _ in range(17):
        code = code*2+bit()
    low, high = 0, 131072

    def decode(table):
        nonlocal low, high, code
        width = high-low
        if not low <= code < high:
            raise LzariError('Invalid arithmetic interval.')
        prob = ((code-low+1)*table[0]-1)//width
        lo, hi = 1, len(table)-1
        while lo < hi:
            mid = (lo+hi)//2
            if prob < table[mid]:
                lo = mid+1
            else:
                hi = mid
        high = low+table[lo-1]*width//table[0]
        low += table[lo]*width//table[0]
        while True:
            if low >= 65536:
                remove = 65536
            elif low >= 32768 and high <= 98304:
                remove = 32768
            elif high <= 65536:
                remove = 0
            else:
                break
            low = (low-remove)*2
            high = (high-remove)*2
            code = (code-remove)*2+bit()
        return lo

    window = bytearray(b' '*4036+bytes(60))
    cursor = 4036
    output = bytearray()
    steps = 0
    while len(output) < size:
        if not steps % 1024:
            check()
        steps += 1
        index = decode(cumulative)
        value = symbols[index]
        # The model halves frequencies before updating the just-decoded
        # symbol. Large control banks reach this limit; short streams never do.
        if cumulative[0] >= 0x7fff:
            total = 0
            for i in range(len(counts)-1, 0, -1):
                cumulative[i] = total
                counts[i] = (counts[i]+1)//2
                total += counts[i]
            cumulative[0] = total
        place = index
        while counts[place] == counts[place-1]:
            place -= 1
        symbols[place], symbols[index] = symbols[index], symbols[place]
        counts[place] += 1
        for i in range(place):
            cumulative[i] += 1
        if value < 256:
            window[cursor] = value
            output.append(value)
            cursor = (cursor+1)&4095
            continue
        source = (cursor-decode(distance))&4095
        length = value-253
        if len(output)+length > size:
            raise LzariError('Arithmetic run exceeds the declared size.')
        for i in range(length):
            value = window[(source+i)&4095]
            window[cursor] = value
            output.append(value)
            cursor = (cursor+1)&4095
    return bytes(output), (position+7)//8
