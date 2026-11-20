"""Pair USO sound-bank descriptors with unique spans in the named wave file."""

import base64
import re
import struct
from collections import defaultdict
from dataclasses import dataclass
from itertools import islice

from .. import formats
from . import audio, ead_font, ead_notes, ead_render, uso_audio_directory
from .uso_textures import _MAGIC, _NAME, _SECTION

_MAX_BANK = 512 * 1024
_MAX_WAVE = 16 * 1024 * 1024
_MAX_SEQUENCE = 256 * 1024
_DESCRIPTOR = struct.Struct('>6I')
_RATE = 22050


@dataclass(frozen=True)
class _Sample:
    offset: int
    size: int
    book: int
    predictors: int
    frame_size: int = 9
    loop: tuple[int, int] = (0, 0)

    @property
    def encoded_size(self):
        return self.size - self.size % self.frame_size


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


def _groups(control, wave_size, check, *, known_font=False):
    groups = defaultdict(list)
    for at in range(16, len(control)-_DESCRIPTOR.size+1, 4):
        if at % 4096 == 0:
            check()
        packed, offset, loop, book, order, predictors = _DESCRIPTOR.unpack_from(control, at)
        size = packed & 0xffffff
        base = at+16-book
        book_size = 8+predictors*32
        flags = packed >> 24
        frame_size = 5 if known_font and flags == 0x30 else 9
        first_descriptor = 16 if known_font else 32
        if (order != 2 or not 1 <= predictors <= 8 or base < 0 or base%16 or at-base < first_descriptor or known_font and base != 0
                or flags not in (0, 2) and frame_size != 5 or not frame_size <= size <= wave_size-offset
                or offset%16 or size%frame_size not in (0, 1)
                or not book+book_size <= loop <= book+book_size+32
                or base+loop+12 > len(control)):
            continue
        first, last, repeat = _SECTION.unpack_from(control, base+loop)
        if not 0 <= first < last <= (size//frame_size+1)*16 or repeat not in (0, 0xffffffff):
            continue
        groups[base].append(_Sample(offset, size, at+24, predictors, frame_size))
    return [list(dict.fromkeys(rows)) for rows in groups.values() if known_font or len(rows) >= 3][:64]


def _fits(wave, base, sample, *, probe=False):
    start = base+sample.offset
    end = start+sample.encoded_size
    if start < 0 or start+sample.size > len(wave):
        return False
    if any(wave[end:start+sample.size]):
        return False
    stop = min(end, start+720) if probe else end
    return all((value & 15) < sample.predictors for value in wave[start:stop:sample.frame_size])


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



def _directory_samples(image, control, wave, directory, check):
    for offset, size, _, _, bank, *_ in directory['fonts']:
        if not size:
            continue
        wave_offset, wave_size, *_ = directory['waves'][bank]
        data = image[wave+wave_offset:wave+wave_offset+wave_size]
        start = control+offset
        groups = _groups(image[start:start+size], len(data), check, known_font=True)
        for rows in groups:
            for row in rows:
                if _fits(data, 0, row):
                    yield start, wave+wave_offset, row


def _font_sample(control, wave, at):
    """Validate a named descriptor even when it shares a nonadjacent book."""
    packed, offset, loop, book = struct.unpack_from('>4I', control, at)
    size, flags = packed & 0xffffff, packed >> 24
    frame = 5 if flags == 0x30 else 9
    if (flags not in (0, 2, 0x30) or not frame <= size <= len(wave)-offset
            or offset % 16 or size % frame not in (0, 1)
            or not 16 <= book <= len(control)-8 or not 16 <= loop <= len(control)-12):
        return None
    order, predictors = struct.unpack_from('>2I', control, book)
    first, last, repeat = _SECTION.unpack_from(control, loop)
    if (order != 2 or not 1 <= predictors <= 8 or book+8+predictors*32 > len(control)
            or not 0 <= first < last <= (size//frame+1)*16 or repeat not in (0, 0xffffffff)):
        return None
    frames = size//frame*16
    looping = (first, last) if repeat and last <= frames else (0, 0)
    sample = _Sample(offset, size, book+8, predictors, frame, looping)
    return sample if _fits(wave, 0, sample) else None


def sequence_voices(image, control, wave, directory, fonts, notes, *, check=lambda: None):
    """Pair timed notes with validated samples, leaving unresolved notes silent."""
    loaded = {}
    for index in dict.fromkeys(fonts):
        offset, size, _, _, bank, other_bank, instruments, drums, high, low = directory['fonts'][index]
        if other_bank != 255:
            continue
        if not size:
            offset, size, *_ = directory['fonts'][offset]
        data = image[control+offset:control+offset+size]
        wave_offset, wave_size, *_ = directory['waves'][bank]
        base = wave+wave_offset
        loaded[index] = data, (instruments, drums, high*256+low), base, image[base:base+wave_size], {}
    voices = {}
    for note in notes:
        font = note.font if note.font is not None else 0
        if not 0 <= font < len(fonts):
            continue
        index = fonts[-1-font]
        if index not in loaded:
            continue
        data, counts, base, waves, samples = loaded[index]
        key = index, note.program, note.key
        if key not in voices:
            voices[key] = ead_font.voice(data, counts, note.program, note.key)
        voice = voices[key]
        if voice is None:
            continue
        if voice.descriptor not in samples:
            check()
            samples[voice.descriptor] = _font_sample(data, waves, voice.descriptor)
        sample = samples[voice.descriptor]
        if sample is not None:
            yield note, voice, sample, data, base


def _guessed_samples(image, control, control_end, wave, wave_end, check, progress):
    data = image[wave:wave_end]
    groups = _groups(image[control:control_end], len(data), check)
    for i, group in enumerate(groups):
        check()
        progress(dict(phase='Matching USO wave tables', done=i, total=len(groups)))
        base = _wave_base(data, group, check)
        if base is not None:
            for row in group:
                yield control, wave+base, row


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
    sequence_range = _payload(image, sequence, formats.MAX_BYTES)
    if not ctl_range or not wave_range or not sequence_range or ctl_range[1] > sequence or sequence_range[1] > wave:
        return []
    ctl_start, ctl_end = ctl_range
    wave_start, wave_end = wave_range
    seq_start, seq_end = sequence_range
    directory = uso_audio_directory.locate(image, ctl_end-ctl_start, seq_end-seq_start, wave_end-wave_start, check=check)
    result = [uso_audio_directory.asset(directory, seq_start)] if directory else []
    if directory:
        stored = [(idx, offset, size) for idx, (offset, size, *_) in enumerate(directory['sequences'])
                  if 0 < size <= _MAX_SEQUENCE]
        result.append(dict(offset=seq_start, size=seq_end-seq_start, label='USO music sequences',
                           kind='music sequence', media='audio', layout='uso-music', confidence='validated',
                           audio_kind='indexed sample directory',
                           sequences=[idx for idx, _, _ in stored],
                           samples=[dict(offset=seq_start+offset, size=size, codec='Nintendo EAD sequence',
                                         label=f'Sequence {idx}', preview_available=True)
                                    for idx, offset, size in stored],
                           sections=[ctl_range, sequence_range, wave_range],
                           reason='Stored EAD sequences use the validated USO instrument and wave tables.',
                           preview_settings=dict(format='auto', source='rom', offset=seq_start)))
    matches = (_directory_samples(image, ctl_start, wave_start, directory, check) if directory
               else _guessed_samples(image, ctl_start, ctl_end, wave_start, wave_end, check, progress))
    samples = {}
    for control, base, row in matches:
        start = base+row.offset
        short = row.frame_size == 5
        samples.setdefault((start, row.size),
                           dict(offset=start, size=row.size, encoded_size=row.encoded_size, rate=_RATE,
                                samples=row.encoded_size//row.frame_size*16,
                                codec='N64 VADPCM (2-bit)' if short else 'N64 VADPCM',
                                bits=2 if short else 4,
                                book_offset=control+row.book, predictors=row.predictors))
    if not samples:
        return result
    entries = sorted(samples.values(), key=lambda sample: sample['offset'])
    for idx, sample in enumerate(entries, 1):
        sample['label'] = f'Sample {idx}'
    reason = ('The EAD loader tables locate the font and wave bank, and every ADPCM frame selector fits its predictor book.'
              if directory else 'Every ADPCM frame selector fits its predictor book at a unique wave-table placement.')
    result.append(dict(offset=bank, size=ctl_end-bank, label='USO sound bank', kind='audio', media='audio',
                 audio_kind='sample bank', layout='uso-audio', confidence='validated', samples=entries,
                 table_confidence='validated', rate_basis='Preview rate',
                 reason=reason+' Preview rate is adjustable.',
                 preview_settings=dict(format='auto', source='rom', offset=bank)))
    return result


def preview(image, asset, selection):
    index = formats.integer(selection.get('sample', 0), 'Sample', 0, len(asset['samples'])-1)
    rate = formats.integer(selection.get('rate', _RATE), 'Preview sample rate', 1000, 192000)
    sample = {**asset['samples'][index], 'rate':rate}
    result = audio.preview(image, {**asset, 'samples':[sample]}, {})
    result['details']['sample'] = index
    result['settings'].update(sample=index, rate=rate)
    return result


def music_preview(image, asset, selection):
    if 'sample' not in selection:
        from .resource_inspection import table

        sequences = asset['sequences']
        return dict(media='metadata', title=asset['label'], fields={'Sequencer':'Nintendo EAD'},
                    table=table(asset['label'], ['index', 'sequence'], len(sequences),
                                lambda i: dict(index=i, sequence=sequences[i]), selection),
                    settings=asset['preview_settings'])
    index = formats.integer(selection['sample'], 'Sequence', 0, len(asset['sequences'])-1)
    sections = asset['sections']
    if len(sections) != 3 or any(not 0 <= start < end <= len(image) for start, end in sections):
        raise formats.AssetError('The audio resources exceed the current ROM. Rescan ROM Explorer.')
    (control, _), (sequence, _), (wave, _) = sections
    directory = uso_audio_directory.locate(image, *(end-start for start, end in sections))
    song = asset['sequences'][index]
    if not directory or not 0 <= song < len(directory['sequences']):
        raise formats.AssetError('The EAD loader tables no longer match the ROM. Rescan ROM Explorer.')
    offset, size, *_ = directory['sequences'][song]
    score = ead_notes.notes(image[sequence+offset:sequence+offset+size]) if 0 < size <= _MAX_SEQUENCE else None
    if score is None:
        raise formats.AssetError('This EAD sequence could not be decoded for playback.')
    voices = sequence_voices(image, control, wave, directory, directory['sequence_fonts'][song], score['notes'])
    pcm, stats = ead_render.render(image, score, voices)
    payload, details = formats.pcm(pcm, dict(format='pcm-s16le', channels=2, rate=ead_render.RATE, length=len(pcm)))
    details.update(stats, format='Nintendo EAD sequence', sample=index, sequence=song,
                   conditional=score['conditional'], incomplete_scripts=score['incomplete'],
                   note='Sample-backed preview. Runtime effects and instrument envelopes can differ.')
    return dict(media='audio', mime='audio/wav', details=details,
                data_url='data:audio/wav;base64,'+base64.b64encode(payload).decode(),
                settings={**asset['preview_settings'], 'sample':index})
