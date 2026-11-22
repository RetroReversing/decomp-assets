"""Direct-color image resources in checked ring-LZSS archives."""

import re
import struct

from .. import formats
from . import lzss_boot

LAYOUT = 'ring-lzss-images'


def archives(image):
    for match in re.finditer(b'LZSS', image):
        base = match.start() - 12
        if base < 0 or base % 4 or base + 8 > len(image):
            continue
        count, reserved = struct.unpack_from('>2I', image, base)
        if not 2 <= count <= 1024 or reserved:
            continue
        table_end = 8 + count * 16
        if base + table_end > len(image):
            continue
        rows = [struct.unpack_from('>I4sII', image, base + 8 + i * 16) for i in range(count)]
        if (any(magic != b'LZSS' or not 0 < size <= lzss_boot._LIMIT or not 0 < packed <= lzss_boot._LIMIT
                or offset < table_end or base + offset + packed > len(image)
                for offset, magic, size, packed in rows)
                or any(a[0] + a[3] > b[0] for a, b in zip(rows, rows[1:]))):
            continue
        yield base, rows


def regions(image, *, check=lambda: None, **kwargs):
    result = []
    for base, rows in archives(image):
        # These repeated full-color images are followed by small companion
        # resources. The 64-by-32 layout is inferred from the image data.
        indexes = [i for i in range(len(rows) - 1) if rows[i][2] == 4096 and rows[i + 1][2] == 512]
        if len(indexes) < 2:
            continue
        for i in indexes:
            offset, _, size, packed = rows[i]
            if lzss_boot.decode(image[base + offset:base + offset + packed], size) is None:
                continue
            result.append(dict(offset=base + offset, size=packed, kind='image', layout=LAYOUT,
                               confidence='validated', label='Compressed direct-color image',
                               width=64, height=32, archive=base, member=i,
                               reason='A bounded LZSS archive contains direct-color pixels; dimensions are inferred.',
                               preview_settings=dict(source='rom', format='auto', offset=base + offset)))
            check()
    return result


def preview(image, asset, selection):
    archive = next((rows for base, rows in archives(image) if base == asset['archive']), None)
    if archive is None or not 0 <= asset['member'] < len(archive):
        raise formats.AssetError('The image archive changed. Rescan ROM Explorer.')
    offset, _, size, packed = archive[asset['member']]
    data = lzss_boot.decode(image[asset['archive'] + offset:asset['archive'] + offset + packed], size)
    if data is None or len(data) != 4096:
        raise formats.AssetError('The compressed image changed. Rescan ROM Explorer.')
    result = formats.preview(data, dict(format='rgba5551-be', offset=0, width=64, height=32))
    result['settings'] = asset['preview_settings']
    result['details']['note'] = asset['reason']
    return result
