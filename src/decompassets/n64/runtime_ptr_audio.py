"""Play cartridge samples whose relocated libmus controls were captured in RAM."""
import base64
import binascii
import itertools
import re
import struct
from collections import Counter

from ..formats import AssetError, integer
from . import audio, ptr_audio

LAYOUT = 'runtime-libmus-controls'


def _pointer(ram, address, size, alignment=4):
    if address >> 29 not in (4, 5):
        return None
    offset = address & 0x1fffffff
    if offset % alignment or offset + size > len(ram):
        return None
    return offset


def _bank(image, ram, at, markers, check):
    """Validate relocated records, predictor books and their cartridge sample frames."""
    if at + 48 > len(ram) or ram[at:at+16] != ptr_audio.MAGIC or int.from_bytes(ram[at+16:at+20], 'big') != 0x80000000:
        return None
    count, notes, tuning, table = struct.unpack_from('>4I', ram, at+32)
    if not 1 <= count <= ptr_audio.MAX_SAMPLES:
        return None
    notes = _pointer(ram, notes, count, 1)
    tuning = _pointer(ram, tuning, count*4)
    table = _pointer(ram, table, count*4)
    if notes is None or tuning is None or table is None:
        return None
    samples, budget = [], ptr_audio.MAX_FRAME_CHECKS
    for index in range(count):
        check()
        address = struct.unpack_from('>I', ram, table+index*4)[0]
        if not address:
            continue
        record = _pointer(ram, address, 20)
        if record is None:
            return None
        start, size, codec, flag, loop, book = struct.unpack_from('>IIBBxxII', ram, record)
        if (codec not in (0, 1) or flag != 1 or not size or size > audio.MAX_BYTES
                or start % 16 or start+size > len(image)):
            return None
        sample = dict(offset=start, size=size, rate=ptr_audio.DEFAULT_RATE,
                      codec='N64 VADPCM' if codec == 0 else 'PCM16 big endian', instrument=index)
        if codec == 0:
            if size < 9 or size % 9 not in (0, 1) or size % 9 == 1 and size % 2:
                return None
            location = _pointer(ram, book, 8)
            if location is None:
                return None
            order, predictors = struct.unpack_from('>II', ram, location)
            if order != 2 or not 1 <= predictors <= 8:
                return None
            nbytes = predictors*32
            if location+8+nbytes > len(ram):
                return None
            encoded = size//9*9
            if any(image[start+encoded:start+size]):
                return None
            for pos in range(start, start+encoded, 9):
                if (pos-start) % (9*1024) == 0:
                    check()
                if budget <= 0 or image[pos] & 15 >= predictors:
                    return None
                budget -= 1
            sample.update(predictors=predictors, samples=size//9*16, encoded_size=encoded,
                          book_data=base64.b64encode(ram[location+8:location+8+nbytes]).decode('ascii'))
        else:
            if size % 2:
                return None
            sample['samples'] = size//2
        if loop:
            location = _pointer(ram, loop, 44 if codec == 0 else 12)
            if location is None:
                return None
            begin, end, repeats = struct.unpack_from('>III', ram, location)
            if not begin <= end <= sample['samples']:
                return None
            sample['loop'] = dict(start=begin, end=end, count=repeats)
        samples.append(sample)
    if not samples:
        return None
    first = min(s['offset'] for s in samples)
    end = max(s['offset']+s['size'] for s in samples)
    candidates = [i for i, marker in enumerate(markers) if marker+16 <= first and
                  (i+1 == len(markers) or end <= markers[i+1])]
    if len(candidates) != 1:
        return None
    return markers[candidates[0]], samples


def regions(image, snapshots, *, check=lambda: None):
    """Require the same complete relocated graph in at least two snapshots."""
    if len(snapshots) < 2:
        return []
    markers = [m.start() for m in itertools.islice(re.finditer(re.escape(ptr_audio.WAVES), image), ptr_audio.MAX_BANKS+1)]
    if not markers or len(markers) > ptr_audio.MAX_BANKS:
        return []
    observations = []
    for ram in snapshots:
        seen = set()
        for hit in itertools.islice(re.finditer(re.escape(ptr_audio.MAGIC), ram), ptr_audio.MAX_BANKS):
            check()
            parsed = _bank(image, ram, hit.start(), markers, check)
            if parsed:
                # The contents, not their RAM address, must recur.
                key = (parsed[0], repr(parsed[1]))
                if key not in seen:
                    observations.append(parsed)
                    seen.add(key)
    signatures = Counter((base, repr(samples)) for base, samples in observations)
    resolved = [(base, samples) for base, samples in observations if signatures[(base, repr(samples))] >= 2]
    by_base = {}
    for base, samples in resolved:
        by_base.setdefault(base, set()).add(repr(samples))
    results, seen_banks = [], set()
    for base, samples in resolved:
        if len(by_base[base]) != 1:
            continue  # Distinct captured controls cannot share one unambiguous preview.
        key = (base, repr(samples))
        if key in seen_banks:
            continue
        seen_banks.add(key)
        reason = ('Repeated RAM snapshots contain the same relocated libmus control graph and predictor books; '
                  'all cartridge sample frames validate against the marked wave table. The preview rate is editable.')
        common = dict(kind='audio', media='audio', audio_kind='runtime libmus sample bank', layout=LAYOUT,
                      confidence='validated', bank_offset=base, table_offset=base, reason=reason,
                      rate_basis='Editable preview rate; not stored in the bank')
        results.append(dict(**common, offset=base, size=16, label='Runtime libmus sample bank', samples=samples,
                            preview_settings=dict(format='auto', source='rom', offset=base)))
        emitted = set()
        for sample in samples:
            extent = sample['offset'], sample['size']
            if extent in emitted:
                continue
            emitted.add(extent)
            results.append(dict(**common, offset=extent[0], size=extent[1], label=sample['codec']+' sample',
                                samples=[sample], preview_settings=dict(format='auto', source='rom', offset=extent[0])))
    return results


def preview(image, asset, selection):
    samples = asset.get('samples', [])
    index = integer(selection.get('sample', 0), 'Sample', 0, len(samples)-1)
    rate = integer(selection.get('rate', ptr_audio.DEFAULT_RATE), 'Preview sample rate', 1000, 192000)
    selected = [{**sample, 'rate': rate} for sample in samples]
    book = None
    if selected[index]['codec'] == 'N64 VADPCM':
        try:
            book = base64.b64decode(selected[index]['book_data'], validate=True)
        except (KeyError, ValueError, binascii.Error) as exc:
            raise AssetError('The captured predictor book is invalid. Rescan ROM Explorer.') from exc
        if len(book) != selected[index]['predictors'] * 32:
            raise AssetError('The captured predictor book is incomplete. Rescan ROM Explorer.')
        selected[index]['book_offset'] = 0
    result = audio.preview(image, {**asset, 'samples': selected}, selection, book_image=book)
    result['settings']['rate'] = rate
    result['details']['rate_basis'] = asset['rate_basis']
    return result
