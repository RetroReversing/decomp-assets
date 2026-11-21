"""Full-screen images followed by cartridge-relative pointers to their strips."""

import re
import struct

_WIDTH = 320
_HEIGHT = 240
_STRIP_BYTES = 0xf00
_FIRST_STRIPS = re.compile(re.escape(struct.pack('>4I', 0, 0xf00, 0x1e00, 0x2d00)))
_ENCODINGS = ((2, 'rgba5551-be'), (1, 'i8'))


def _group(image, base):
    rows = []
    start = base
    for stride, encoding in _ENCODINGS:
        pixel_bytes = _WIDTH * _HEIGHT * stride
        strips = pixel_bytes // _STRIP_BYTES
        while True:
            table = start + pixel_bytes
            end = table + strips * 4
            if end > len(image):
                break
            pointers = struct.iter_unpack('>I', image[table:end])
            if any(pointer != start-base + slot*_STRIP_BYTES
                   for slot, (pointer,) in enumerate(pointers)):
                break
            rows.append((start, pixel_bytes, encoding))
            start = end
    return rows


def regions(image, *, check=lambda: None, progress=lambda _: None):
    assets = []
    for anchor in _FIRST_STRIPS.finditer(image):
        check()
        base = anchor.start() - _WIDTH * _HEIGHT * 2
        if base < 0x40 or base % 8:
            continue
        rows = _group(image, base)
        # Require independent, consecutive image tables before interpreting raw pixels.
        if len(rows) < 3:
            continue
        for start, size, encoding in rows:
            settings = dict(format=encoding, source='rom', offset=start, width=_WIDTH, height=_HEIGHT)
            assets.append(dict(kind='image', offset=start, size=size, label=f'Striped image {len(assets)+1}',
                               confidence='validated', layout='striped-image', width=_WIDTH, height=_HEIGHT,
                               reason='The strip table gives a cartridge pointer to every row group.',
                               preview_settings=settings))
    return assets
