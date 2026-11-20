"""Pair USO sound-bank descriptors with unique spans in the named wave file."""

import re
import struct
from collections import defaultdict
from dataclasses import dataclass
from itertools import islice

from .. import formats
from . import audio
from .uso_textures import _MAGIC, _NAME, _SECTION

_MAX_BANK = 512 * 1024
_MAX_WAVE = 16 * 1024 * 1024
_DESCRIPTOR = struct.Struct('>6I')
_RATE = 22050


@dataclass(frozen=True)
class _Sample:
    offset: int
    size: int
    book: int
    predictors: int

    @property
    def encoded_size(self):
        return self.size - self.size % 9


def _payload(image, named, limit):
    module = named+40
    start = module+4+_SECTION.size
    if start > len(image) or image[module:module+4] != _MAGIC:
        return None
    kind, size, _ = _SECTION.unpack_from(image, module+4)
    end = start+size
    if kind != 6 or not 0 < size <= limit or end+_SECTION.size > len(image):
        return None
    if image[start:start+4] == b'Yay0' or _SECTION.unpack_from(image, end)[0] != 1:
        return None
    return start, end


def _groups(control, wave_size, check):
    groups = defaultdict(list)
    for at in range(16, len(control)-_DESCRIPTOR.size+1, 4):
        if at % 4096 == 0:
            check()
        packed, offset, loop, book, order, predictors = _DESCRIPTOR.unpack_from(control, at)
        size = packed & 0xffffff
        base = at+16-book
        book_size = 8+predictors*32
        if (order != 2 or not 1 <= predictors <= 8 or base < 0 or base%16 or at-base < 32
                or packed >> 24 not in (0, 2) or not 9 <= size <= wave_size-offset
                or offset%16 or size%9 not in (0, 1)
                or not book+book_size <= loop <= book+book_size+32
                or base+loop+12 > len(control)):
            continue
        first, last, repeat = _SECTION.unpack_from(control, base+loop)
        if not 0 <= first < last <= (size//9+1)*16 or repeat not in (0, 0xffffffff):
            continue
        groups[base].append(_Sample(offset, size, at+24, predictors))
    return [list(dict.fromkeys(rows)) for rows in groups.values() if len(rows) >= 3][:64]


def _fits(wave, base, sample, *, probe=False):
    start = base+sample.offset
    end = start+sample.encoded_size
    if start < 0 or start+sample.size > len(wave):
        return False
    if any(wave[end:start+sample.size]):
        return False
    stop = min(end, start+720) if probe else end
    return all((value & 15) < sample.predictors for value in wave[start:stop:9])


def _wave_base(wave, samples, check):
    ordered = sorted(samples, key=lambda row: (row.predictors, -row.size))
    anchor = next((row for row in ordered if row.encoded_size >= 90), None)
    if anchor is None:
        return None
    valid = re.escape(bytes(value for value in range(256) if (value & 15) < anchor.predictors))
    signature = re.compile(rb'(?=(?:['+valid+rb'].{8}){9}['+valid+rb'])', re.S)
    identified = None
    candidates = probes = 0
    for hit in signature.finditer(wave, anchor.offset):
        probes += 1
        if probes % 1024 == 0:
            check()
        base = hit.start()-anchor.offset
        if base%16:
            continue
        if not all(_fits(wave, base, sample, probe=True) for sample in ordered):
            continue
        candidates += 1
        if candidates > 4096:
            return None
        if all(_fits(wave, base, sample) for sample in ordered):
            if identified is not None:
                return None
            identified = base
    return identified


def regions(image, *, check=lambda: None, progress=lambda _: None):
    files = {}
    for item in islice(_NAME.finditer(image), 1024):
        if item[1] in (b'audio_bank.uso', b'audio_seq.uso', b'audio_wave.uso'):
            files.setdefault(item[1], []).append(item.start())
    if len(files) != 3 or any(len(offsets) != 1 for offsets in files.values()):
        return []
    bank, sequence, wave = (files[name][0] for name in (b'audio_bank.uso', b'audio_seq.uso', b'audio_wave.uso'))
    ids = [_SECTION.unpack_from(image, at)[1] for at in (bank, sequence, wave)]
    if not bank < sequence < wave or ids != list(range(ids[0], ids[0]+3)):
        return []
    ctl_range = _payload(image, bank, _MAX_BANK)
    wave_range = _payload(image, wave, _MAX_WAVE)
    if not ctl_range or not wave_range or ctl_range[1] > sequence:
        return []
    ctl_start, ctl_end = ctl_range
    wave_start, wave_end = wave_range
    waves = image[wave_start:wave_end]
    rows = _groups(image[ctl_start:ctl_end], len(waves), check)
    samples = {}
    for i, group in enumerate(rows):
        check()
        progress(dict(phase='Matching USO wave tables', done=i, total=len(rows)))
        base = _wave_base(waves, group, check)
        if base is None:
            continue
        for row in group:
            start = wave_start+base+row.offset
            samples.setdefault((start, row.size),
                               dict(offset=start, size=row.size, encoded_size=row.encoded_size, rate=_RATE,
                                    samples=row.encoded_size//9*16, codec='N64 VADPCM',
                                    book_offset=ctl_start+row.book, predictors=row.predictors))
    if not samples:
        return []
    entries = sorted(samples.values(), key=lambda sample: sample['offset'])
    for idx, sample in enumerate(entries, 1):
        sample['label'] = f'Sample {idx}'
    return [dict(offset=bank, size=ctl_end-bank, label='USO sound bank', kind='audio', media='audio',
                 audio_kind='sample bank', layout='uso-audio', confidence='validated', samples=entries,
                 table_confidence='validated', rate_basis='Preview rate',
                 reason='Named USO controls and wave data. Every ADPCM frame selector fits its stored predictor book at a unique wave-table placement. Preview rate is adjustable.',
                 preview_settings=dict(format='auto', source='rom', offset=bank))]


def preview(image, asset, selection):
    index = formats.integer(selection.get('sample', 0), 'Sample', 0, len(asset['samples'])-1)
    rate = formats.integer(selection.get('rate', _RATE), 'Preview sample rate', 1000, 192000)
    sample = {**asset['samples'][index], 'rate':rate}
    result = audio.preview(image, {**asset, 'samples':[sample]}, {})
    result['details']['sample'] = index
    result['settings'].update(sample=index, rate=rate)
    return result
