"""JPEG previews for named Huffman-coded N64 image resources."""

import re
import struct

from .. import formats
from . import named_resources

LAYOUT = 'named-resource-huff'
_DIMENSIONS = {300: (320, 240), 9: (48, 48)}
_HEADER = re.compile(rb'HUFF(?:\x01\x2c|\x00\x09)')
# JPEG's standard luminance quantizer in raster order. The RSP uses it for
# every component, scaled by the shift selected by the image loader.
_QUANT = (
    16,11,10,16,24,40,51,61, 12,12,14,19,26,58,60,55,
    14,13,16,24,40,57,69,56, 14,17,22,29,51,87,80,62,
    18,22,37,56,68,109,103,77, 24,35,55,64,81,104,113,92,
    49,64,78,87,103,121,120,101, 72,92,95,98,112,100,103,99,
)
_ZIGZAG = sorted(range(64), key=lambda i: (sum(divmod(i, 8)), (i//8) * (1 if sum(divmod(i, 8))%2 else -1)))
_COUNTS = (
    (0,1,5,1,1,1,1,1,1,0,0,0,0,0,0,0),
    (0,3,1,1,1,1,1,1,1,1,1,0,0,0,0,0),
    (0,2,1,3,3,2,4,3,5,5,4,4,0,0,1,125),
    (0,2,1,2,4,4,3,4,7,5,4,4,0,1,2,119),
)
_TABLE_SPACING = (0, 0x40, 0x80, 0x1f0)


def _tables(image):
    sig = struct.pack('>16H12H', *_COUNTS[0], *range(12))
    first = image.find(sig, 0, min(len(image), 0x100000))
    if first < 0 or first+_TABLE_SPACING[-1]+356 > len(image):
        return []
    output = []
    for relative, counts in zip(_TABLE_SPACING, _COUNTS):
        table = first+relative
        if struct.unpack_from('>16H', image, table) != counts:
            return []
        symbols = struct.unpack_from(f'>{sum(counts)}H', image, table+32)
        if max(symbols) > 255 or len(set(symbols)) != len(symbols):
            return []
        lookup, code, index = {}, 0, 0
        for width, count in enumerate(counts, 1):
            for _ in range(count):
                lookup[width, code] = symbols[index]
                code += 1
                index += 1
            code <<= 1
        output.append((bytes(counts)+bytes(symbols), lookup))
    return output


class _Bits:
    def __init__(self, data):
        self.data = data
        self.position = 0

    def read(self, count):
        byte, shift = divmod(self.position, 8)
        if self.position+count > len(self.data)*8:
            raise formats.AssetError('The compressed image ends inside a coefficient.')
        end = (shift+count+7)//8
        self.position += count
        return (int.from_bytes(self.data[byte:byte+end], 'big') >> (end*8-shift-count)) & ((1 << count)-1)

    def symbol(self, table):
        code = 0
        for width in range(1, 17):
            code = code*2 + self.read(1)
            if (width, code) in table:
                return table[width, code]
        raise formats.AssetError('The compressed image contains an invalid Huffman symbol.')


class _Writer:
    def __init__(self):
        self.data = bytearray()
        self.bits = 0
        self.used = 0

    def write(self, width, value):
        self.bits = self.bits << width | value
        self.used += width
        while self.used >= 8:
            self.used -= 8
            self.data.append(self.bits >> self.used)
            self.bits &= (1 << self.used)-1

    def symbol(self, table, value):
        if value not in table:
            raise formats.AssetError('The image contains a coefficient that cannot be encoded.')
        self.write(*table[value])

    def finish(self):
        padding = -self.used % 8
        self.write(padding, (1 << padding)-1)
        return bytes(self.data)


_TRANSPOSE = tuple(_ZIGZAG.index((point%8)*8 + point//8) for point in _ZIGZAG)


def _block(bits, writer, dc, ac, encode_dc, encode_ac, bias):
    size = bits.symbol(dc)
    value = bits.read(size)
    if bias:
        coefficient = value if not size or value >= 1 << (size-1) else value-((1 << size)-1)
        delta = coefficient-bias
        size = abs(delta).bit_length()
        value = delta if delta >= 0 else delta+(1 << size)-1
    writer.symbol(encode_dc, size)
    writer.write(size, value)
    coefficients = {}
    index = 1
    while index < 64:
        run = bits.symbol(ac)
        if not run:
            break
        index += run >> 4
        width = run & 15
        if index >= 64 or not width and run != 0xf0:
            raise formats.AssetError('The compressed image has an invalid coefficient run.')
        if width:
            coefficients[_TRANSPOSE[index]] = (width, bits.read(width))
        index += 1
    previous = 0
    for position, (width, value) in sorted(coefficients.items()):
        zeros = position-previous-1
        for _ in range(zeros//16):
            writer.symbol(encode_ac, 0xf0)
        writer.symbol(encode_ac, (zeros%16 << 4) | width)
        writer.write(width, value)
        previous = position
    if previous < 63:
        writer.symbol(encode_ac, 0)


def _scan(data, count, tables, bias):
    bits, writer = _Bits(data), _Writer()
    lookup = [table for _, table in tables]
    encode = [{value: key for key, value in table.items()} for table in lookup]
    # The RSP transposes each block before its IDCT and emits unsigned samples.
    # JPEG uses raster coefficients and adds 128 after applying its IDCT.
    for macroblock in range(count):
        for block in range(6):
            chroma = int(block >= 4)
            initial = bias if macroblock == 0 and block in (0, 4, 5) else 0
            _block(bits, writer, lookup[chroma], lookup[chroma+2], encode[chroma], encode[chroma+2], initial)
    return writer.finish()


def _jpeg(data, tables, shift):
    count = int.from_bytes(data[4:6], 'big')
    if not data.startswith(b'HUFF') or count not in _DIMENSIONS:
        raise formats.AssetError('The named image header is unsupported. Rescan ROM Explorer.')
    width, height = _DIMENSIONS[count]
    quantization = bytes(_QUANT[index] >> shift for index in _ZIGZAG)
    entropy = _scan(data[6:], count, tables, 1024//quantization[0])

    def marker(kind, body):
        return struct.pack('>BBH', 255, kind, len(body)+2) + body

    return (b'\xff\xd8' + marker(0xdb, b'\0'+quantization)
            + marker(0xc0, struct.pack('>BHHB', 8, height, width, 3)+bytes.fromhex('012200021100031100'))
            + marker(0xc4, b''.join(bytes([kind])+table for kind,(table,_) in zip((0,1,16,17), tables)))
            + marker(0xda, bytes.fromhex('03010002110311003f00'))
            + entropy.replace(b'\xff', b'\xff\0') + b'\xff\xd9')


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for name, packed, start, end in named_resources.members(image, check):
        if packed or image[start:start+4] != b'HUFF' or end-start < 8:
            continue
        starts = [match.start() for match in _HEADER.finditer(image, start, end) if match.start()%4 == 0]
        for index, (offset, stop) in enumerate(zip(starts, [*starts[1:], end])):
            check()
            count = int.from_bytes(image[offset+4:offset+6], 'big')
            width, height = _DIMENSIONS[count]
            label = f'{name} · Image {index+1}' if len(starts)>1 else name
            result.append(dict(offset=offset, size=stop-offset, kind='image', confidence='validated', layout=LAYOUT,
                               label=label, shift=2 if count==300 and name.startswith('x') else 1,
                               reason='The named resource bounds a Huffman-coded image in 16-pixel blocks.',
                               preview_settings=dict(format='auto', source='rom', offset=offset, width=width, height=height)))
    return result if result and _tables(image) else []


def preview(image, asset, selection):
    start, size = asset['offset'], asset['size']
    tables = _tables(image)
    if not tables:
        raise formats.AssetError('The resident Huffman tables changed. Rescan ROM Explorer.')
    data = _jpeg(image[start:start+size], tables, asset['shift'])
    result = formats.preview(data, {'format':'auto'})
    result['settings'] = asset['preview_settings']
    result['details']['note'] = asset['reason']
    return result
