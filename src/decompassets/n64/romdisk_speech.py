"""Indexed MORT speech stored as a ROM disk member."""
import base64
import struct

from .. import formats
from . import mort, romdisk

LAYOUT = 'romdisk-mort-speech'


def clips(data):
    if len(data) < 8:
        return []
    count = int.from_bytes(data[:4], 'big')
    if not 1 <= count <= 4096 or 4+count*4 > len(data):
        return []
    offsets = struct.unpack_from(f'>{count}I', data, 4)
    if offsets[0] < 4+count*4 or any(a >= b for a, b in zip(offsets, offsets[1:])):
        return []
    found = []
    for i, start in enumerate(offsets):
        end = offsets[i+1] if i+1 < count else len(data)
        if start+12 > end or end > len(data):
            return []
        magic, frames, rate, words = mort.HEADER.unpack_from(data, start)
        if magic != b'MORT' or not frames or not 4000 <= rate <= 48000 or words*4 != end-start:
            return []
        found.append(dict(relative_offset=start, size=end-start, rate=rate, samples=frames*mort.SAMPLES_PER_FRAME,
                          codec='Factor 5 MORT', label=f'Clip {i+1}', preview_available=True))
    return found


def regions(image, *, check=lambda: None, **kwargs):
    result = []
    for group in romdisk.members(image, check):
        for member in group:
            if not member['name'].lower().endswith('.mdir'):
                continue
            try:
                data = romdisk.unpack(image, member)
            except formats.AssetError:
                continue
            rows = clips(data)
            if rows:
                result.append(dict(**member, kind='audio', media='audio', layout=LAYOUT,
                                   label=member['name'], confidence='validated', audio_kind='speech',
                                   sample_count=len(rows), samples=rows,
                                   reason='The archive member bounds an ordered directory of MORT clips.',
                                   preview_settings=dict(source='rom', format='auto', offset=member['offset'])))
    return result


def preview(image, asset, selection):
    data = romdisk.unpack(image, asset)
    rows = clips(data)
    if not rows:
        raise formats.AssetError('The speech directory changed. Rescan ROM Explorer.')
    index = formats.integer(selection.get('sample', 0), 'Clip', 0, len(rows)-1)
    sample = rows[index]
    start, size, rate = sample['relative_offset'], sample['size'], sample['rate']
    frames = min(sample['samples']//mort.SAMPLES_PER_FRAME, rate*formats.MAX_SECONDS//mort.SAMPLES_PER_FRAME)
    pcm = mort.decode(data[start:start+size], frames)
    wav, details = formats.pcm(pcm, dict(format='pcm-s16le', rate=rate, length=len(pcm)))
    details.update(format=sample['codec'], sample=index, original_samples=sample['samples'],
                   truncated=len(pcm)//2 < sample['samples'], note=asset['reason'])
    return dict(media='audio', mime='audio/wav', data_url='data:audio/wav;base64,'+base64.b64encode(wav).decode(),
                details=details, settings=dict(asset['preview_settings'], sample=index))
