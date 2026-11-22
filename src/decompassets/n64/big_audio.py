"""Sample streams indexed inside a paged archive and stored in a paired raw file."""

import re
import struct

from .. import formats

LAYOUT = 'big-indexed-audio'
_RATE = 22050
_STEP = (7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45, 50, 55,
         60, 66, 73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190, 209, 230, 253, 279, 307,
         337, 371, 408, 449, 494, 544, 598, 658, 724, 796, 876, 963, 1060, 1166, 1282, 1411,
         1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327, 3660, 4026, 4428, 4871, 5358,
         5894, 6484, 7132, 7845, 8630, 9493, 10442, 11487, 12635, 13899, 15289, 16818, 18500,
         20350, 22385, 24623, 27086, 29794, 32767, 32767, 32767, 32767, 32767, 32767, 32767, 32767)
_DELTA = (10, 8, 6, 4, 2, -1, -1, -1, -1, -1, -1, -1, 2, 4, 6, 8)


def _rows(data):
    for match in re.finditer(b'idx\0', data):
        at = match.start()
        if at + 12 > len(data):
            continue
        size, = struct.unpack_from('<I', data, at + 4)
        count, = struct.unpack_from('>I', data, at + 8)
        if not 2 <= count <= 4096 or size != count * 20 + 4 or at + 8 + size > len(data):
            continue
        rows = [struct.unpack_from('>5I', data, at + 8 + index * 20) for index in range(count)]
        if (rows[0][2] != 0 or any(not length or length % 68 or flags not in (0, 1)
                                    for _, _, _, length, flags in rows)
                or any(left[2] + left[3] != right[2] for left, right in zip(rows, rows[1:]))):
            continue
        yield rows


def _raw_file(image, archive, length):
    matches = set()
    for big in re.finditer(rb'[A-Za-z0-9_-]{1,11}\.[bB][iI][gG]\x00', image):
        at = big.start()
        if at + 32 > len(image) or image[at+16:at+20] != bytes(4) or image[at+28:at+32] != bytes(4):
            continue
        size, relative = struct.unpack_from('>2I', image, at + 20)
        if size != archive[2][-1] >> 4 or relative > archive[0]:
            continue
        base = archive[0] - relative
        for raw in re.finditer(b'big.raw\0', image):
            entry = raw.start()
            if (abs(entry - at) > 0x10000 or (entry - at) % 32 or entry + 32 > len(image)
                    or image[entry+16:entry+20] != bytes(4) or image[entry+28:entry+32] != bytes(4)):
                continue
            raw_size, raw_offset = struct.unpack_from('>2I', image, entry + 20)
            start = base + raw_offset
            if raw_size == length and 0 <= start <= len(image) - raw_size:
                matches.add(start)
    return next(iter(matches)) if len(matches) == 1 else None


def from_archive(image, archive, data, check=lambda: None):
    result = []
    for rows in _rows(data):
        total = rows[-1][2] + rows[-1][3]
        start = _raw_file(image, archive, total)
        if start is None or any(image[start+i+4] > 88 for i in range(0, total, 68)):
            continue
        check()
        samples = [dict(label=f'Sample {number}', offset=start+offset, size=length,
                        samples=length//68*128, rate=_RATE, codec='Predictive 4-bit stream')
                   for _, number, offset, length, _ in rows]
        result.append(dict(offset=start, size=total, kind='audio', media='audio', audio_kind='sample bank',
                           layout=LAYOUT, confidence='validated', samples=samples, rate_basis='Preview rate',
                           reason='An indexed sample table and its paired raw file agree on every bounded audio block. '
                                  'Preview rate is adjustable.',
                           preview_settings=dict(source='rom', format='auto', offset=start, sample=0, rate=_RATE)))
    return result


def _block(data):
    if len(data) != 68:
        raise formats.AssetError('The audio block is truncated. Rescan ROM Explorer.')
    previous, current = struct.unpack_from('>2h', data)
    mode = previous & 3
    previous &= ~3
    index = data[4]
    out = [previous, current]
    for byte in data[5:]:
        for value in (byte >> 4, byte & 15):
            nibble = value if value < 8 else value - 16
            if index >= len(_STEP):
                raise formats.AssetError('The audio predictor is invalid. Rescan ROM Explorer.')
            if mode == 0:
                predicted = 0
            elif mode == 1:
                predicted = current
            elif mode == 2:
                predicted = (3 * current - previous) >> 1
            else:
                predicted = 2 * current - previous
            decoded = max(-32768, min(32767, predicted + nibble * _STEP[index]))
            previous, current = current, decoded
            out.append(current)
            index = max(0, index + _DELTA[nibble + 8])
    return struct.pack('>128h', *out)


def preview(image, asset, selection):
    index = formats.integer(selection.get('sample', 0), 'Sample', 0, len(asset['samples']) - 1)
    rate = formats.integer(selection.get('rate', _RATE), 'Preview sample rate', 1000, 192000)
    sample = asset['samples'][index]
    start, size = sample['offset'], sample['size']
    if start < asset['offset'] or size % 68 or start + size > asset['offset'] + asset['size'] or start + size > len(image):
        raise formats.AssetError('The audio stream changed. Rescan ROM Explorer.')
    pcm = b''.join(_block(image[at:at+68]) for at in range(start, start + size, 68))
    result = formats.preview(pcm, dict(format='pcm-s16be', channels=1, rate=rate, length=len(pcm)))
    result['details'].update(sample=index, codec='Predictive 4-bit stream', note=asset['reason'])
    result['settings'] = dict(asset['preview_settings'], sample=index, rate=rate)
    return result
