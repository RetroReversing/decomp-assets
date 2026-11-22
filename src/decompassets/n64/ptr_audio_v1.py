"""Unrelocated libmus pointer tables with the original header."""
import re
import struct

from .. import formats
from . import audio, ptr_audio

MAGIC = b'N64 PtrTables  \0'
LAYOUT = 'libmus-v1-samples'


def bank(image, at, check=lambda: None):
    if image[at:at+16] != MAGIC or at+20 > len(image):
        return None
    count = int.from_bytes(image[at+16:at+20], 'big')
    if not 1 <= count <= 1024 or at+20+count*4 > len(image):
        return None
    end = at+20+count*4
    rows = []
    for index in range(count):
        check()
        pointer = int.from_bytes(image[at+20+4*index:at+24+4*index], 'big')
        record = at+pointer
        if pointer % 4 or pointer < 20+count*4 or record+20 > len(image):
            return None
        base, size, codec, flags, loop, book = struct.unpack_from('>IIBBxxII', image, record)
        if (base < 16 or base % 16 or not 9 <= size <= formats.MAX_BYTES or codec or flags
                or size % 9 not in (0, 1) or size % 9 == 1 and size % 2
                or book % 4 or book < 20+count*4 or at+book+8 > len(image)):
            return None
        order, predictors = struct.unpack_from('>II', image, at+book)
        if order != 2 or not 1 <= predictors <= 8 or at+book+8+predictors*32 > len(image):
            return None
        end = max(end, record+20, at+book+8+predictors*32)
        item = dict(relative_offset=base, size=size, codec='N64 VADPCM', rate=22050,
                    book_offset=at+book+8, predictors=predictors, encoded_size=size//9*9,
                    samples=size//9*16, instrument=index)
        if loop:
            if loop % 4 or loop < 20+count*4 or at+loop+44 > len(image):
                return None
            start, finish, repeat = struct.unpack_from('>III', image, at+loop)
            if not start <= finish <= item['samples']:
                return None
            item['loop'] = dict(start=start, end=finish, count=repeat)
            end = max(end, at+loop+44)
        rows.append(item)
    return dict(offset=at, size=end-at, samples=rows)


def regions(image, *, check=lambda: None, **kwargs):
    found = []
    waves = [m.start() for m in re.finditer(re.escape(ptr_audio.WAVES), image)]
    for hit in re.finditer(re.escape(MAGIC), image):
        at = hit.start()
        info = bank(image, at, check)
        if not info:
            continue
        fits = [base for base in waves if ptr_audio.fits(image, info, base, [4*1024*1024], check)]
        if len(fits) != 1:
            continue
        base = fits[0]
        rows = [dict(s, offset=base+s['relative_offset'], label=f'Sample {i+1}', preview_available=True)
                for i, s in enumerate(info['samples'])]
        found.append(dict(offset=at, size=info['size'], kind='audio', media='audio', layout=LAYOUT,
                          label='libmus sample bank', confidence='validated', audio_kind='sample bank',
                          sample_count=len(rows), samples=rows, table_offset=base,
                          reason='Every pointer, predictor book, loop and ADPCM frame fits the uniquely matching marked wave table. Preview rate is adjustable.',
                          preview_settings=dict(source='rom', format='auto', offset=at)))
    return found


def preview(image, asset, selection):
    info = bank(image, asset['offset'])
    if info is None or len(info['samples']) != asset['sample_count']:
        raise formats.AssetError('The pointer bank changed. Rescan ROM Explorer.')
    rate = formats.integer(selection.get('rate', 22050), 'Sample rate', 1000, 192000)
    rows = [dict(s, offset=asset['table_offset']+s['relative_offset'], rate=rate) for s in info['samples']]
    return audio.preview(image, {**asset, 'samples': rows}, selection)
