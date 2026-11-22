"""ADPCM controls with relative wave records in compressed RNC resources."""
import re
import struct

from .. import formats, rnc
from . import audio

LAYOUT = 'rnc-adpcm-samples'
_BOOK = b'\0\0\0\2\0\0\0\4'


def samples(data):
    rows = []
    for hit in re.finditer(_BOOK, data):
        at = hit.start()
        if at < 24 or at % 4 or at+136 > len(data):
            continue
        base, size = struct.unpack_from('>II', data, at-24)
        if (int.from_bytes(data[at-8:at-4], 'big') != 0x4000+at or any(data[at-16:at-8])
                or base % 8 or not 9 <= size <= 131072 or size % 9 not in (0, 1)):
            continue
        rows.append(dict(relative_offset=base, size=size, book_offset=at+8, predictors=4,
                         encoded_size=size//9*9, samples=size//9*16, codec='N64 VADPCM', rate=22050))
    return rows if 8 <= len(rows) <= 512 else []


def wave_base(image, rows, check=lambda: None):
    limit = len(image)-max(x['relative_offset']+x['size'] for x in rows)
    matches = []
    for base in range(0, limit+1, 8):
        if base % 65536 == 0:
            check()
        nonzero = 0
        for row in rows:
            at = base+row['relative_offset']
            length = min(row['encoded_size'], 180)
            head = image[at:at+length]
            if not any(head):
                continue
            nonzero += 1
            if (any((head[i] & 15) >= 4 or head[i] >> 4 > 12 for i in range(0, length, 9))
                    or row['size'] % 9 and image[at+row['size']-1]):
                break
        else:
            if nonzero < 8:
                continue
            valid = True
            for row in rows:
                at = base+row['relative_offset']
                if any((image[at+i] & 15) >= 4 or image[at+i] >> 4 > 12
                       for i in range(0, row['encoded_size'], 9)):
                    valid = False
                    break
            if valid:
                matches.append(base)
                if len(matches) > 1:
                    return None
    return matches[0] if matches else None


def regions(image, *, check=lambda: None, **kwargs):
    found = []
    for hit in re.finditer(b'RNC\x01', image):
        check()
        at = hit.start()
        try:
            data, size = rnc.unpack_at(image, at)
        except rnc.RncError:
            continue
        rows = samples(data)
        if not rows:
            continue
        base = wave_base(image, rows, check)
        if base is None:
            continue
        listed = [dict(row, offset=base+row['relative_offset'], label=f'Sample {i+1}', preview_available=True)
                  for i, row in enumerate(rows)]
        found.append(dict(offset=at, size=size, kind='audio', media='audio', layout=LAYOUT,
                          label='RNC ADPCM sample bank', confidence='inferred', audio_kind='N64 sample bank',
                          table_confidence='inferred', rate_basis='Preview rate',
                          wave_offset=base, sample_count=len(listed), samples=listed,
                          reason='Compressed sound records and predictor books uniquely fit the frame boundaries in the sample area. Preview rate is adjustable.',
                          preview_settings=dict(source='rom', format='auto', offset=at)))
    return found


def preview(image, asset, selection):
    try:
        data, _ = rnc.unpack_at(image, asset['offset'])
    except rnc.RncError as error:
        raise formats.AssetError('The compressed sound bank changed. Rescan ROM Explorer.') from error
    rows = samples(data)
    if not rows or len(rows) != asset['sample_count']:
        raise formats.AssetError('The sound records changed. Rescan ROM Explorer.')
    rate = formats.integer(selection.get('rate', 22050), 'Sample rate', 1000, 192000)
    listed = [dict(row, offset=asset['wave_offset']+row['relative_offset'], rate=rate) for row in rows]
    return audio.preview(image, {**asset, 'samples': listed}, selection, book_image=data)
