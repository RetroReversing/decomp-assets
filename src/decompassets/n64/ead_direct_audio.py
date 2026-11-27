"""EAD control, sequence and wave directories with explicit ROM extents."""

import re
import struct

from .. import formats
from . import audio, uso_audio, uso_audio_directory

LAYOUT = 'ead-direct-samples'
_HEADER = re.compile(rb'\0[\x01-\x80]\0{14}')
_ENTRY = struct.Struct('>II8B')


def _table(image, at):
    if at + 16 > len(image):
        return None
    count = int.from_bytes(image[at:at+2], 'big')
    end = at + 16 + count*16
    if not 1 <= count <= 128 or any(image[at+2:at+16]) or end > len(image):
        return None
    rows = list(_ENTRY.iter_unpack(image[at+16:end]))
    if any(row[2] != 2 or row[3] > 4 for row in rows):
        return None
    return rows, end


def directories(image, check=lambda: None):
    for match in _HEADER.finditer(image):
        seq_at = match.start()
        if seq_at % 16 or not (sequences := _table(image, seq_at)):
            continue
        if not (waves_table := _table(image, sequences[1])):
            continue
        waves, at = waves_table
        if at + 24 > len(image):
            continue
        ctl, ctl_end, wave, wave_end, seq, seq_end = struct.unpack_from('>6I', image, at)
        if not (at+24 <= ctl < ctl_end <= seq < seq_end <= wave < wave_end <= len(image)):
            continue
        if not (uso_audio_directory._entries(image, seq_at, seq_end-seq, aliases=True)
                and uso_audio_directory._entries(image, sequences[1], wave_end-wave, aliases=False)):
            continue
        candidates = []
        for earlier in _HEADER.finditer(image, max(0, seq_at-8192), seq_at):
            start = earlier.start()
            if start % 16 or not (fonts := uso_audio_directory._entries(image, start, ctl_end-ctl, aliases=True)):
                continue
            rows, end = fonts
            if (end <= seq_at and all(row[4] < len(waves) and (row[5] == 255 or row[5] < len(waves))
                                      for row in rows)):
                candidates.append((start, rows))
        if len(candidates) == 1:
            check()
            start, fonts = candidates[0]
            yield start, fonts, waves, ctl, wave, at + 24


def contiguous_directories(image, check=lambda: None):
    """Find consecutive font, wave and sequence payloads immediately after their linked tables.

    Some EAD programs omit the six explicit ROM extents. Their three complete
    tables and sequence-to-font map instead bound three consecutive payloads.
    Sound fonts and ADPCM frames are validated separately before exposing audio.
    """
    for hit in _HEADER.finditer(image):
        sequence_at = hit.start()
        if sequence_at % 16 or not (sequences := _table(image, sequence_at)):
            continue
        sequence_rows, wave_at = sequences
        if len(sequence_rows) < 3 or not (waves_table := _table(image, wave_at)):
            continue
        waves, control = waves_table
        if len(waves) < 2:
            continue
        seq_size = sum(row[1] for row in sequence_rows)
        wave_size = sum(row[1] for row in waves)
        if (not 0 < seq_size <= len(image) or not 0 < wave_size <= len(image)
                or not uso_audio_directory._entries(image, sequence_at, seq_size, aliases=True)
                or not uso_audio_directory._entries(image, wave_at, wave_size, aliases=False)):
            continue
        candidates = []
        for earlier in _HEADER.finditer(image, max(0, sequence_at-8192), sequence_at):
            font_at = earlier.start()
            if font_at % 16 or not (font_table := _table(image, font_at)):
                continue
            fonts, map_at = font_table
            control_size = sum(row[1] for row in fonts)
            if (len(fonts) < 3 or not 0 < control_size <= len(image)
                    or not uso_audio_directory._entries(image, font_at, control_size, aliases=True)
                    or any(row[4] >= len(waves) or row[5] != 255 and row[5] >= len(waves) for row in fonts)
                    or uso_audio_directory._fonts(image, map_at, sequence_at, len(sequence_rows), len(fonts)) is None):
                continue
            wave = control+control_size
            sequence = wave+wave_size
            if sequence+seq_size <= len(image):
                candidates.append((font_at, fonts, waves, control, wave, control))
        if len(candidates) == 1:
            check()
            yield candidates[0]


def regions(image, *, check=lambda: None, **kwargs):
    result = []
    found = (*directories(image, check), *contiguous_directories(image, check))
    for start, fonts, waves, control, wave, end in found:
        samples = {}
        for row in fonts:
            offset, size = row[:2]
            if not size:
                continue
            font = image[control+offset:control+offset+size]
            bank_ids = {row[4], row[5]} - {255}
            wave_size = max((waves[i][1] for i in bank_ids), default=0)
            groups = uso_audio._groups(font, wave_size, check, known_font=True)
            for group in groups:
                for sample in group:
                    bases = [wave + waves[i][0] for i in bank_ids
                             if sample.offset + sample.size <= waves[i][1]
                             and uso_audio._fits(image, wave + waves[i][0], sample)]
                    if len(bases) != 1:
                        continue
                    base = bases[0]
                    short = sample.frame_size == 5
                    key = base+sample.offset, sample.size
                    samples[key] = dict(offset=key[0], size=sample.size, encoded_size=sample.encoded_size,
                                        rate=32000, samples=sample.encoded_size//sample.frame_size*16,
                                        codec='N64 VADPCM (2-bit)' if short else 'N64 VADPCM',
                                        bits=2 if short else 4, book_offset=control+offset+sample.book,
                                        predictors=sample.predictors)
        if not samples:
            continue
        entries = sorted(samples.values(), key=lambda item: item['offset'])
        for index, item in enumerate(entries, 1):
            item['label'] = f'Sample {index}'
        result.append(dict(offset=start, size=end-start, kind='audio', media='audio', layout=LAYOUT,
                           audio_kind='sample bank', label=f'EAD sample bank ({len(entries)} samples)',
                           confidence='validated', samples=entries, rate_basis='Preview rate',
                           reason='The directory bounds the sound fonts and wave banks; every frame selector fits its predictor book. Preview rate is adjustable.',
                           preview_settings=dict(format='auto', source='rom', offset=start)))
    return result


def preview(image, asset, selection):
    index = formats.integer(selection.get('sample', 0), 'Sample', 0, len(asset['samples'])-1)
    rate = formats.integer(selection.get('rate', 32000), 'Preview sample rate', 1000, 192000)
    sample = {**asset['samples'][index], 'rate': rate}
    result = audio.preview(image, {**asset, 'samples': [sample]}, {})
    result['details']['sample'] = index
    result['settings'].update(sample=index, rate=rate)
    return result
