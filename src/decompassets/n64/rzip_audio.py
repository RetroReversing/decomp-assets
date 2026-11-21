"""MPEG Layer III streams in indexed cartridge resource banks."""

import base64

from .. import formats
from . import rzip_catalog

LAYOUT = 'rzip-catalog-mpeg'
_RATES = {0: (11025, 12000, 8000), 2: (22050, 24000, 16000), 3: (44100, 48000, 32000)}
_MPEG1 = (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0)
_MPEG2 = (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0)


def stream(data, *, preview=False):
    offset, frames, count, rate, samples = 0, bytearray(), 0, None, 0
    while offset + 4 <= len(data):
        a, b, c, d = data[offset:offset + 4]
        version, layer, bitrate, frequency = (b >> 3) & 3, (b >> 1) & 3, c >> 4, (c >> 2) & 3
        if (a != 0xff or b & 0xe0 != 0xe0 or version not in _RATES or layer != 1
                or bitrate in (0, 15) or frequency == 3):
            break
        current_rate = _RATES[version][frequency]
        if rate is not None and current_rate != rate:
            return None
        rate = current_rate
        kbps = (_MPEG1 if version == 3 else _MPEG2)[bitrate]
        length = (144000 if version == 3 else 72000) * kbps // rate + ((c >> 1) & 1)
        if length < 4 or offset + length > len(data):
            return None
        frame = data[offset:offset + length]
        offset += length
        if d & 8:
            # The native decoder consumes a nine-byte, NUL-terminated cue
            # after this frame. It is metadata, not part of the MPEG bitstream.
            cue = data[offset:offset + 9]
            if len(cue) != 9 or cue[:2] != b'L:' or cue[-1] != 0 or 0 in cue[:-1]:
                return None
            offset += 9
        count += 1
        frame_samples = 1152 if version == 3 else 576
        if preview and samples < rate * 30 and len(frames) + length <= formats.MAX_BYTES:
            frames.extend(frame)
        samples += frame_samples
        if count > 100000:
            return None
    if count < 8 or rate is None:
        return None
    return dict(rate=rate, samples=samples, frames=count, bytes=bytes(frames),
                consumed=offset, truncated=preview and samples > rate * 30)


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for _, indexed, _ in rzip_catalog.catalogs(image, check=check):
        samples = []
        for start, end, flags in indexed:
            check()
            if flags & 1:
                continue
            data = memoryview(image)[start:end]
            if data[:1] != b'\xff':
                continue
            found = stream(data)
            if found:
                samples.append(dict(offset=start, size=end-start, codec='MPEG Layer III', rate=found['rate'],
                                    samples=found['samples'], preview_available=True))
        if samples:
            start = samples[0]['offset']
            end = samples[-1]['offset'] + samples[-1]['size']
            result.append(dict(offset=start, size=end-start, kind='audio', media='audio', layout=LAYOUT,
                               audio_kind='indexed sample directory', label=f'{len(samples)} MPEG streams',
                               confidence='validated', samples=samples, sample_count=len(samples),
                               reason='Each indexed entry contains a checked sequence of MPEG Layer III frames.',
                               preview_settings=dict(format='auto', source='rom', offset=start)))
    return result


def preview(image, asset, selection):
    index = formats.integer(selection.get('sample', 0), 'Sample', 0, len(asset['samples']) - 1)
    sample = asset['samples'][index]
    start, end = sample['offset'], sample['offset'] + sample['size']
    if not 0 <= start < end <= len(image) or not (found := stream(image[start:end], preview=True)):
        raise formats.AssetError('The audio stream changed. Rescan ROM Explorer.')
    if found['rate'] != sample['rate'] or found['samples'] != sample['samples']:
        raise formats.AssetError('The audio stream changed. Rescan ROM Explorer.')
    return dict(media='audio', mime='audio/mpeg',
                data_url='data:audio/mpeg;base64,' + base64.b64encode(found['bytes']).decode('ascii'),
                details=dict(format='MPEG Layer III', rate=found['rate'], samples=found['samples'],
                             sample=index, truncated=found['truncated'],
                             note='Embedded cue records are omitted from the playable MPEG stream.'),
                settings=dict(asset['preview_settings'], sample=index))
