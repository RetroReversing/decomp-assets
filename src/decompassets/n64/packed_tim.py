"""BAM3 sprite archives compressed with adaptive Huffman coding and a 4 KiB dictionary."""

import re
import struct

from .. import formats

LAYOUT = 'n64-packed-tim'
# Initial adaptive Huffman codes for the four BAM3 signature bytes.
_SIGNATURE = re.compile(rb'\xe7\x73\x7b\x3b[\xf8-\xff]')
_LENGTH = struct.Struct('>I')
_RECTANGLE = struct.Struct('<I4H')
_SYMBOLS = 314
_TREE_SIZE = 2 * _SYMBOLS - 1
_ROOT = _TREE_SIZE - 1
_TIM_FORMATS = {2: 'TIM BGR555', 3: 'TIM RGB24', 8: 'TIM CI4', 9: 'TIM CI8'}
_MAX_BANKS = 512
_MAX_TOTAL = 32 * 1024 * 1024
_POSITION_LENGTHS = (3,) + (4,) * 3 + (5,) * 8 + (6,) * 12 + (7,) * 24 + (8,) * 16


def _positions():
    values = []
    for high, length in enumerate(_POSITION_LENGTHS):
        values.extend([(high << 6, length - 2)] * (1 << (8 - length)))
    return tuple(values)


_POSITIONS = _positions()


class _Bits:
    def __init__(self, data):
        self.data = data
        self.cursor = self.available = self.buffer = 0

    def take(self, count):
        if self.available < count:
            if self.cursor >= len(self.data):
                raise formats.AssetError('The packed image bank ends inside a code.')
            self.buffer = self.buffer << 8 | self.data[self.cursor]
            self.cursor += 1
            self.available += 8
        self.available -= count
        value = self.buffer >> self.available
        self.buffer &= (1 << self.available) - 1
        return value


class _Tree:
    def __init__(self):
        self.weights = [1] * _SYMBOLS + [0] * (_TREE_SIZE - _SYMBOLS) + [65535]
        self.children = list(range(_TREE_SIZE, _TREE_SIZE + _SYMBOLS))
        self.children.extend(range(0, 2 * (_TREE_SIZE - _SYMBOLS), 2))
        self.parents = [0] * (_TREE_SIZE + _SYMBOLS)
        for index in range(_SYMBOLS, _TREE_SIZE):
            child = self.children[index]
            self.weights[index] = self.weights[child] + self.weights[child + 1]
        for index in range(_TREE_SIZE):
            self._link(index)

    def _link(self, index):
        child = self.children[index]
        self.parents[child] = index
        if child < _TREE_SIZE:
            self.parents[child + 1] = index

    def _rescale(self):
        leaves = [((self.weights[i] + 1) >> 1, child)
                  for i, child in enumerate(self.children) if child >= _TREE_SIZE]
        for index, (weight, child) in enumerate(leaves):
            self.weights[index], self.children[index] = weight, child
        for index in range(_SYMBOLS, _TREE_SIZE):
            child = 2 * (index - _SYMBOLS)
            weight = self.weights[child] + self.weights[child + 1]
            slot = index
            while self.weights[slot - 1] > weight:
                slot -= 1
            self.weights[slot + 1:index + 1] = self.weights[slot:index]
            self.children[slot + 1:index + 1] = self.children[slot:index]
            self.weights[slot], self.children[slot] = weight, child
        for index in range(_TREE_SIZE):
            self._link(index)

    def read(self, bits):
        child = self.children[_ROOT]
        while child < _TREE_SIZE:
            child = self.children[child + bits.take(1)]
        if self.weights[_ROOT] == 32768:
            self._rescale()
        index = self.parents[child]
        while True:
            weight = self.weights[index] + 1
            slot = index
            while weight > self.weights[slot + 1]:
                slot += 1
            self.weights[index], self.weights[slot] = self.weights[slot], weight
            if slot != index:
                self.children[index], self.children[slot] = self.children[slot], self.children[index]
                self._link(index)
                self._link(slot)
            index = self.parents[slot]
            if not index:
                return child - _TREE_SIZE


def _unpack(data, size, check):
    bits = _Bits(data)
    tree = _Tree()
    output = bytearray()
    next_check = 0
    while len(output) < size:
        if len(output) >= next_check:
            check()
            next_check = len(output) + 4096
        symbol = tree.read(bits)
        if symbol < 256:
            output.append(symbol)
            continue
        length = symbol - 253
        if len(output) + length > size:
            raise formats.AssetError('A packed image bank match exceeds its declared size.')
        head = bits.take(8)
        high, extra = _POSITIONS[head]
        distance = (high | ((head << extra | bits.take(extra)) & 63)) + 1
        for _ in range(length):
            output.append(output[-distance] if len(output) >= distance else 0)
    return output, bits.cursor


def _rectangle(data, offset):
    if offset + _RECTANGLE.size > len(data):
        return None
    size, _, _, words, rows = _RECTANGLE.unpack_from(data, offset)
    if words and rows and size == _RECTANGLE.size + words * rows * 2 and offset + size <= len(data):
        return offset + _RECTANGLE.size, offset + size, words, rows
    return None


def _tim(data):
    if len(data) < 20 or data[:4] != b'\x10\0\0\0':
        return None
    mode = int.from_bytes(data[4:8], 'little')
    if mode not in (2, 3, 8, 9):
        return None
    offset = 8
    colors = palette = palettes = 0
    if mode in (8, 9):
        colors = 16 if mode == 8 else 256
        rectangle = _rectangle(data, offset)
        if not rectangle:
            return None
        palette, offset, columns, rows = rectangle
        if columns % colors or columns * rows // colors > 256:
            return None
        palettes = columns * rows // colors
    rectangle = _rectangle(data, offset)
    if not rectangle:
        return None
    pixels, end, words, height = rectangle
    width = {2: words, 3: words * 2 // 3, 8: words * 4, 9: words * 2}[mode]
    if (not 0 < width <= formats.MAX_DIMENSION or height > formats.MAX_DIMENSION
            or width * height > formats.MAX_PIXELS or end != len(data)):
        return None
    return dict(width=width, height=height, words=words, mode=mode, pixels=pixels,
                palette_offset=palette, colors=colors, palettes=palettes)


def _members(bank):
    if len(bank) < 12 or bank[:4] != b'BAM3':
        return []
    table_end = _LENGTH.unpack_from(bank, 4)[0]
    if table_end % 4 or not 12 <= table_end <= min(len(bank), 16384):
        return []
    ends = [offset for offset, in _LENGTH.iter_unpack(bank[4:table_end])]
    if ends[-1] != len(bank) or any(start >= end for start, end in zip(ends, ends[1:])):
        return []
    textures = []
    for index, (start, end) in enumerate(zip(ends, ends[1:]), 1):
        info = _tim(memoryview(bank)[start:end])
        if info:
            textures.append(dict(label=f'TIM image {index}', palettes=info['palettes'], frames=1,
                                 member_start=start, member_end=end,
                                 preview_settings=dict(format=_TIM_FORMATS[info['mode']],
                                                       width=info['width'], height=info['height'])))
    return textures


def regions(image, *, check=lambda: None, progress=lambda _: None):
    found = []
    expanded = 0
    for index, match in enumerate(_SIGNATURE.finditer(image)):
        check()
        if index >= _MAX_BANKS or expanded >= _MAX_TOTAL:
            break
        offset = match.start() - 4
        if offset < 0 or offset % 4:
            continue
        size = _LENGTH.unpack_from(image, offset)[0]
        if not 12 <= size <= min(formats.MAX_BYTES, _MAX_TOTAL - expanded):
            continue
        expanded += size
        try:
            bank, consumed = _unpack(memoryview(image)[offset + 4:offset + 4 + formats.MAX_BYTES], size, check)
        except formats.AssetError:
            continue
        if textures := _members(bank):
            found.append(dict(offset=offset, size=consumed + 4, kind='image', media='image', layout=LAYOUT,
                              label='BAM3 texture bank', confidence='validated', textures=textures,
                              palettes=textures[0]['palettes'], frames=1, expanded_size=size,
                              reason='The compressed bank expands to a BAM3 directory with valid TIM images.',
                              preview_settings=dict(source='rom', offset=offset, **textures[0]['preview_settings'])))
    return found


def _bgr555(value):
    return bytes(((value & 31) * 255 // 31, (value >> 5 & 31) * 255 // 31,
                  (value >> 10 & 31) * 255 // 31, 0 if not value else 255))


def _pixels(data, info, palette):
    start = info['pixels']
    if info['mode'] in (8, 9):
        at = info['palette_offset'] + palette * info['colors'] * 2
        colors = [_bgr555(value) for value, in struct.iter_unpack('<H', data[at:at + info['colors'] * 2])]
        if info['mode'] == 8:
            return b''.join(colors[index] for value in data[start:] for index in (value & 15, value >> 4))
        return b''.join(colors[index] for index in data[start:])
    if info['mode'] == 2:
        return b''.join(_bgr555(value) for value, in struct.iter_unpack('<H', data[start:]))
    stride = info['words'] * 2
    return b''.join(bytes((*data[row + column:row + column + 3], 255))
                    for row in range(start, len(data), stride)
                    for column in range(0, info['width'] * 3, 3))


def preview(image, asset, selection):
    for key in ('frame', 'mip'):
        formats.integer(selection.get(key, 0), key.capitalize(), 0, 0)
    textures = asset['textures']
    texture = textures[formats.integer(selection.get('texture', 0), 'Texture', 0, len(textures) - 1)]
    palette = formats.integer(selection.get('palette', 0), 'Palette', 0, max(0, texture['palettes'] - 1))
    offset = asset['offset']
    bank, _ = _unpack(memoryview(image)[offset + 4:offset + asset['size']], asset['expanded_size'], lambda: None)
    data = memoryview(bank)[texture['member_start']:texture['member_end']]
    info = _tim(data)
    if not info:
        raise formats.AssetError('The TIM image changed. Rescan ROM Explorer.')
    png = formats._png(info['width'], info['height'], _pixels(data, info, palette))
    result = formats.preview(png, {'format': 'auto'})
    result['settings'] = dict(asset['preview_settings'], width=info['width'], height=info['height'])
    return result
