"""Predictive sound effects in paged tagged sample resources."""

import re
import struct

from .. import formats
from . import big_pages

LAYOUT = 'big-sam-audio'
_COEFFICIENTS = ((256, 0), (512, -256), (0, 0), (192, 64), (240, 0), (460, -208), (392, -232))
_SCALE = (230, 230, 230, 230, 307, 409, 512, 614, 768, 614, 512, 409, 307, 230, 230, 230)


def _sample(data, at):
    if at + 40 > len(data) or data[at:at+4] != b'SAM\0':
        return None
    size, = struct.unpack_from('<I', data, at + 4)
    if size < 32 or at + 8 + size > len(data):
        return None
    flags, count, _, _, rate, marker, block_samples, stride = struct.unpack_from('>8I', data, at + 8)
    if (flags != 5 or not 1 <= count <= 2_000_000 or not 1000 <= rate <= 192000
            or marker != 0x80000000 or block_samples != 60 or stride != 32):
        return None
    full, remainder = divmod(count, block_samples)
    length = full * stride + (2 + (remainder + 1) // 2 if remainder else 0)
    if size - 32 - length not in range(4):
        return None
    start = at + 40
    if any((int.from_bytes(data[start+i*stride:start+i*stride+2], 'little') & 7) >= len(_COEFFICIENTS)
           for i in range(full + bool(remainder))):
        return None
    return size, count, rate, length


def from_archive(image, archive, data, check=lambda: None):
    found = []
    for match in re.finditer(b'SAM\0', data):
        at = match.start()
        sample = _sample(data, at)
        if not sample:
            continue
        size, count, rate, _ = sample
        lo, hi = big_pages.physical(archive, at, size + 8)
        found.append(dict(label=f'Sample {len(found)+1}', offset=lo, size=hi-lo, resource=at,
                          resource_size=size, samples=count, rate=rate, codec='Predictive 4-bit sample'))
        check()
    if not found:
        return []
    start = min(sample['offset'] for sample in found)
    end = max(sample['offset'] + sample['size'] for sample in found)
    return [dict(offset=start, size=end-start, kind='audio', media='audio', audio_kind='sample bank',
                 layout=LAYOUT, confidence='validated', table_confidence='validated', samples=found,
                 archive=archive[0], label='Paged sound effects',
                 reason='Tagged sample records provide the encoded blocks, sample count and playback rate.',
                 preview_settings=dict(source='rom', format='auto', offset=start, sample=0))]


def _decode(data, count):
    output = []
    previous = older = 0
    for start in range(0, count, 60):
        amount = min(60, count-start)
        offset = (start // 60) * 32
        word = int.from_bytes(data[offset:offset+2], 'little')
        mode, scale = word & 7, word & ~7
        if mode >= len(_COEFFICIENTS) or offset + 2 + (amount+1)//2 > len(data):
            raise formats.AssetError('The sound effect is truncated or has an invalid predictor.')
        c0, c1 = _COEFFICIENTS[mode]
        for i in range(amount):
            byte = data[offset+2+i//2]
            value = byte >> 4 if i % 2 == 0 else byte & 15
            nibble = value if value < 8 else value-16
            decoded = max(-32768, min(32767, ((c0*previous + c1*older) >> 8) + nibble*scale))
            older, previous = previous, decoded
            output.append(decoded)
            scale = max(8, (scale * _SCALE[value]) >> 8)
    return struct.pack(f'>{len(output)}h', *output)


def preview(image, asset, selection):
    index = formats.integer(selection.get('sample', 0), 'Sample', 0, len(asset['samples'])-1)
    sample = asset['samples'][index]
    archive = next((item for item in big_pages.archives(image) if item[0] == asset['archive']), None)
    if not archive or not (data := big_pages.extract(image, archive, sample['resource'], sample['resource_size'] + 8)):
        raise formats.AssetError('The sound archive changed. Rescan ROM Explorer.')
    found = _sample(data, 0)
    if not found or found[1] != sample['samples'] or found[2] != sample['rate']:
        raise formats.AssetError('The sound effect changed. Rescan ROM Explorer.')
    pcm = _decode(data[40:40+found[3]], found[1])
    result = formats.preview(pcm, dict(format='pcm-s16be', channels=1, rate=sample['rate'], length=len(pcm)))
    result['details'].update(sample=index, codec=sample['codec'], note=asset['reason'])
    result['settings'] = dict(asset['preview_settings'], sample=index)
    return result
