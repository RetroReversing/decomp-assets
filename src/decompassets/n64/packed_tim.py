"""TIM sprite archives compressed with adaptive Huffman coding and a 4 KiB dictionary."""

import re
import struct

from .. import formats

LAYOUT = 'n64-packed-tim'
# Initial adaptive Huffman codes for BAM3 and the big-endian directory tag 0x100.
_SIGNATURE = re.compile(rb'\xe7\x73\x7b\x3b[\xf8-\xff]|\xc6\x62\xe3')
_LENGTH = struct.Struct('>I')
_RECTANGLE = struct.Struct('<I4H')
_NATIVE_RECTANGLE = struct.Struct('>I4H')
_NATIVE_FORMATS = {2: 'rgba5551-be', 8: 'ci4', 9: 'ci8'}
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


def _rectangle(data, offset, header, *, padded=False):
    if offset + header.size > len(data):
        return None
    size, _, _, words, rows = header.unpack_from(data, offset)
    pixels = offset + header.size
    end = offset + size
    visible_end = pixels + words * rows * 2
    if not words or not rows or end > len(data):
        return None
    if visible_end != end:
        padded_end = pixels + words * ((rows + 31) & ~31) * 2
        if not padded or not visible_end < end == padded_end:
            return None
        # The loader uploads only the declared rows. Corroborate the padded
        # rectangle by requiring the extra rows to have one repeated index.
        padding = data[visible_end:end]
        if any(value != padding[0] for value in padding):
            return None
    return pixels, end, words, rows


def _tim(data, native=False):
    order = 'big' if native else 'little'
    header = _NATIVE_RECTANGLE if native else _RECTANGLE
    if len(data) < 20 or int.from_bytes(data[:4], order) != 16:
        return None
    mode = int.from_bytes(data[4:8], order)
    if mode not in (_NATIVE_FORMATS if native else _TIM_FORMATS):
        return None
    offset = 8
    colors = palette = palettes = 0
    if mode in (8, 9):
        colors = 16 if mode == 8 else 256
        rectangle = _rectangle(data, offset, header)
        if not rectangle:
            return None
        palette, offset, columns, rows = rectangle
        if columns % colors or columns * rows // colors > 256:
            return None
        palettes = columns * rows // colors
    if (native and palettes and len(data) == offset + header.size
            and (size := header.unpack_from(data, offset))[0] == header.size and size[-2:] == (0, 0)):
        return dict(width=colors, height=1, mode=mode, pixels=palette, palette_offset=palette,
                    colors=colors, palettes=palettes, palette_only=True)
    rectangle = _rectangle(data, offset, header, padded=native and mode == 9)
    if not rectangle:
        return None
    pixels, end, words, height = rectangle
    width = {2: words, 3: words * 2 // 3, 8: words * 4, 9: words * 2}[mode]
    if (not 0 < width <= formats.MAX_DIMENSION or height > formats.MAX_DIMENSION
            or width * height > formats.MAX_PIXELS or end != len(data)):
        return None
    return dict(width=width, height=height, words=words, mode=mode, pixels=pixels,
                palette_offset=palette, colors=colors, palettes=palettes)


def _members(bank, native=False):
    if len(bank) < 12:
        return []
    if native:
        tag, count = struct.unpack_from('>2I', bank)
        table_end = 8 + count * 4
        if tag != 0x100 or not 1 <= count <= 4096 or table_end >= len(bank):
            return []
        ends = [offset for offset, in _LENGTH.iter_unpack(bank[8:table_end])] + [len(bank)]
        if ends[0] != table_end:
            return []
    else:
        table_end = _LENGTH.unpack_from(bank, 4)[0]
        if bank[:4] != b'BAM3' or table_end % 4 or not 12 <= table_end <= min(len(bank), 16384):
            return []
        ends = [offset for offset, in _LENGTH.iter_unpack(bank[4:table_end])]
        if ends[-1] != len(bank):
            return []
    if any(start >= end for start, end in zip(ends, ends[1:])):
        return []
    labels = _NATIVE_FORMATS if native else _TIM_FORMATS
    textures = []
    for index, (start, end) in enumerate(zip(ends, ends[1:]), 1):
        info = _tim(memoryview(bank)[start:end], native)
        if info:
            palette_only = info.get('palette_only', False)
            label = f'TIM palette {index}' if palette_only else f'TIM image {index}'
            fmt = 'palette-rgba5551' if palette_only else labels[info['mode']]
            textures.append(dict(label=label, palettes=info['palettes'], frames=1,
                                 member_start=start, member_end=end,
                                 preview_settings=dict(format=fmt, width=info['width'], height=info['height'])))
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
        native = bank[:4] == b'\x00\x00\x01\x00'
        if textures := _members(bank, native):
            found.append(dict(offset=offset, size=consumed + 4, kind='image', media='image', layout=LAYOUT,
                              label='Big-endian TIM bank' if native else 'BAM3 texture bank',
                              confidence='validated', textures=textures, native_tim=native,
                              palettes=textures[0]['palettes'], frames=1, expanded_size=size,
                              reason='The compressed directory bounds TIM member dimensions, palettes, and pixel data.',
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
    # The app closes its mapped ROM as soon as this call returns. A frame
    # retained by tracing or an exception must not keep that mapping exported.
    packed = formats._take(image, offset + 4, asset['size'] - 4)
    bank, _ = _unpack(packed, asset['expanded_size'], lambda: None)
    data = memoryview(bank)[texture['member_start']:texture['member_end']]
    native = asset.get('native_tim', False)
    info = _tim(data, native)
    if not info:
        raise formats.AssetError('The TIM image changed. Rescan ROM Explorer.')
    settings = texture['preview_settings']
    if native:
        # The runtime copies the big-endian RGBA5551 palettes and the
        # high-nibble-first indices directly to the N64 texture buffers.
        palette_at = info['palette_offset'] + palette * info['colors'] * 2
        pixels_at = palette_at if info.get('palette_only') else info['pixels']
        result = formats.preview(data, dict(settings, offset=pixels_at, palette_offset=palette_at))
        result['details']['note'] = asset['reason']
    else:
        png = formats._png(info['width'], info['height'], _pixels(data, info, palette))
        result = formats.preview(png, {'format': 'auto'})
    result['settings'] = dict(asset['preview_settings'], **{k: settings[k] for k in ('width', 'height')})
    return result
