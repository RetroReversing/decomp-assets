"""SDF2 sample directories with per-sample N64 ADPCM predictor books."""

import re
import struct

from . import audio

LAYOUT = 'sdf2-audio'
_HEADER = re.compile(rb'SDF2....BTEN', re.S)
_ENTRY = struct.Struct('>6I')
_BOOK = 160  # Loop history followed by four order-2 predictor books.


def _bank(image, start, check):
    if start+16 > len(image):
        return None
    table_size, count = struct.unpack_from('>I4xI', image, start+4)
    if not 2 <= count <= 4096 or not 16+count*_ENTRY.size <= table_size <= len(image)-start:
        return None
    samples = []
    next_offset = table_size
    for index in range(count):
        if index % 64 == 0:
            check()
        size, loop_start, loop_end, relative, rate, looping = _ENTRY.unpack_from(image, start+16+index*_ENTRY.size)
        encoded = size//9*9
        book = start+relative
        offset = book+_BOOK
        if (relative != next_offset or size < 9 or size%9 not in (0, 8) or not 4000 <= rate <= 96000
                or looping not in (0, 1) or not loop_start <= loop_end <= ((size+8)//9)*16
                or offset+size > len(image)):
            return None
        if any(image[at] & 15 >= 4 for at in range(offset, offset+encoded, 9)):
            return None
        sample = dict(offset=offset, size=size, encoded_size=encoded, samples=encoded//9*16,
                      codec='N64 VADPCM', rate=rate, book_offset=book+32, predictors=4)
        if looping:
            sample['loop'] = dict(start=loop_start, end=loop_end, count=-1)
        samples.append(sample)
        next_offset = relative+_BOOK+size
    return table_size, samples


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for match in _HEADER.finditer(image):
        start = match.start()
        check()
        if start % 4 or not (bank := _bank(image, start, check)):
            continue
        table_size, samples = bank
        reason = ('The native directory supplies the sample bounds, playback rate and four predictor books. '
                  'An incomplete final ADPCM frame is omitted; looping is not reproduced.')
        common = dict(kind='audio', media='audio', audio_kind='sample bank', layout=LAYOUT,
                      confidence='validated', reason=reason)
        result.append(dict(common, offset=start, size=table_size, label='SDF2 sample bank', samples=samples,
                           preview_settings=dict(source='rom', format='auto', offset=start)))
        for index, sample in enumerate(samples):
            result.append(dict(common, offset=sample['offset'], size=sample['size'],
                               label=f'SDF2 sample {index+1}', samples=[sample],
                               preview_settings=dict(source='rom', format='auto', offset=sample['offset'])))
    return result


def preview(image, asset, selection):
    return audio.preview(image, asset, selection)
