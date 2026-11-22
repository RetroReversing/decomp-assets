"""Bounded BNKb instrument records with embedded N64 predictor books."""
from . import audio

LAYOUT = 'bnkb-samples'


def regions(image, *, check=lambda: None, **kwargs):
    result = []
    at = 0
    while (at := image.find(b'BNKb', at)) >= 0:
        start = at
        at += 4
        if start + 20 > len(image) or image[start+4] not in (2, 4):
            continue
        count = int.from_bytes(image[start+6:start+8], 'big')
        table = start + (12 if image[start+4] == 2 else 20)
        waves = int.from_bytes(image[start+8:start+12], 'big')
        if not 1 <= count <= 512 or waves < table-start+4*count or start+waves >= len(image):
            continue
        pointers = []
        for i in range(count):
            p = table+4*i
            if p+4 > len(image):
                break
            rel = int.from_bytes(image[p:p+4], 'big')
            target = p+rel
            if rel and not (table+4*count <= target < start+waves and image[target:target+2] == b'PT'):
                break
            pointers.append(target if rel else 0)
        if len(pointers) != count:
            continue
        entries = {}
        ends = sorted({p for p in pointers if p} | {start+waves})
        for p in ends[:-1]:
            check()
            end = ends[ends.index(p)+1]
            record = image[p:min(end, p+512)]
            base = record.find(b'\x88\x04')
            book = record.find(b'\x8f\x88\x00\x00\x00\x02')
            rate = record.find(b'\x84\x02')
            length2 = record.find(b'\x85\x02')
            length3 = record.find(b'\x85\x03')
            if min(base, book, rate) < 0 or max(base+6, book+10, rate+4) > len(record):
                continue
            if length2 >= 0 and length2+4 <= len(record):
                samples = int.from_bytes(record[length2+2:length2+4], 'big')
            elif length3 >= 0 and length3+5 <= len(record):
                samples = int.from_bytes(record[length3+2:length3+5], 'big')
            else:
                continue
            relative = int.from_bytes(record[base+2:base+6], 'big')
            frequency = int.from_bytes(record[rate+2:rate+4], 'big')
            predictors = int.from_bytes(record[book+6:book+10], 'big')
            size = ((samples+15)//16)*9
            pos = start+relative
            if (relative < waves or not 1000 <= frequency <= 64000 or not 1 <= predictors <= 8
                    or not 0 < samples <= 1000000 or book+10+predictors*32 > len(record)
                    or pos+size > len(image)):
                continue
            if any((image[n] & 15) >= predictors for n in range(pos, pos+size, 9)):
                continue
            entries[pos, size] = dict(offset=pos, size=size, encoded_size=size, samples=samples,
                                      rate=frequency, codec='N64 VADPCM', predictors=predictors,
                                      book_offset=p+book+10)
        if not entries:
            continue
        samples = sorted(entries.values(), key=lambda s: s['offset'])
        for i, sample in enumerate(samples, 1):
            sample['label'] = f'Sample {i}'
        result.append(dict(offset=start, size=waves, kind='audio', media='audio', layout=LAYOUT,
                           audio_kind='sample bank', label=f'BNKb sample bank ({len(samples)} samples)',
                           confidence='validated', samples=samples,
                           reason='Instrument records locate their samples, sample rates and predictor books.',
                           preview_settings=dict(format='auto', source='rom', offset=start)))
    return result


def preview(image, asset, selection):
    return audio.preview(image, asset, selection)
