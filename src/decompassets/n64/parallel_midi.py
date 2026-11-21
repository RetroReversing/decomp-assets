"""Compact MIDI with parallel arrays of absolute sequence starts and ends."""

import re
import struct
from itertools import islice, pairwise

from .. import formats
from . import audio, compact_midi, uv_sequences

LAYOUT = 'parallel-compact-midi'
_WORD = struct.Struct('>I')


def _rows(image, index, first, check):
    starts = [first]
    for step in range(1, 129):
        check()
        pos = index + 4 * step
        if pos + 4 > first:
            return [], []
        at = _WORD.unpack_from(image, pos)[0]
        if at <= starts[-1]:
            break
        if at >= len(image) or at % 16 or at - starts[-1] > 256 * 1024:
            return [], []
        starts.append(at)
    else:
        return [], []
    if len(starts) < 3:
        return [], []
    size = 4 * (len(starts) - 1)
    if pos + size + 4 > first or image[index + 4:index + 4 + size] != image[pos:pos + size]:
        return [], []
    end = _WORD.unpack_from(image, pos + size)[0]
    if not (starts[-1] < end <= min(len(image), starts[-1] + 256 * 1024)
            and image[end:end + 2] == b'B1'):
        return [], []
    rows, scores = [], []
    remaining_events = 256 * 1024
    for start, stop in pairwise((*starts, end)):
        check()
        score = compact_midi.sequence(image[start:stop])
        if score is None:
            return [], []
        division, events = score
        remaining_events -= len(events)
        if remaining_events < 0:
            return [], []
        notes = sum(event.status & 0xf0 == 0x90 and event.duration > 0 and event.data[1] > 0 for event in events)
        rows.append(dict(offset=start, size=stop - start, division=division, notes=notes))
        scores.append(events)
    return rows, scores


def _wave_bounds(bank):
    return max(sample['relative_offset'] + sample['size'] for sample in bank['samples'])


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    limit = min(len(image), 0x200000)
    for control, relocated in islice(audio._candidates(image), audio.MAX_CANDIDATES):
        check()
        if relocated:
            continue
        try:
            bank = audio.bank(image, control, check=check)
        except audio.BankError:
            continue
        if not bank['samples']:
            continue
        adjacent = (control + bank['size'] + 15) & ~15
        waves = _wave_bounds(bank)
        for base in range(adjacent, adjacent + 65, 16):
            first = (base + waves + 15) & ~15
            if (first + 68 >= len(image) or any(image[base + waves:first])
                    or image[first:first + 4] != b'\0\0\0D'):
                continue
            marker = re.compile(re.escape(_WORD.pack(first)))
            for match in islice(marker.finditer(image, 0, min(first, limit)), 64):
                index = match.start()
                if index % 4:
                    continue
                rows, scores = _rows(image, index, first, check)
                if not rows or not uv_sequences._bank_covers(scores, bank['programs']):
                    continue
                if not audio._fits(image, dict(bank, corroborated=True), base, [audio.MAX_HEADER_CHECKS], check):
                    continue
                end = rows[-1]['offset'] + rows[-1]['size']
                asset = uv_sequences._asset(first, end, rows, 'Compact MIDI tracks',
                                            'Parallel offsets bound every sequence and the instrument bank supplies its voices.',
                                            control)
                asset.update(layout=LAYOUT, index=index, table_offset=base)
                result.append(asset)
                break
    return result


def preview(image, asset, selection):
    index = formats.integer(selection.get('sample', 0), 'Sequence', 0, len(asset['sequences']) - 1)
    base = asset['table_offset']
    try:
        bank = audio.bank(image, asset['control'])
    except audio.BankError as exc:
        raise formats.AssetError('The Compact MIDI instrument bank changed. Rescan ROM Explorer.') from exc
    source = asset['offset']
    rows, scores = _rows(image, asset['index'], source, lambda: None)
    if (rows != asset['sequences'] or not bank['samples'] or (base + _wave_bounds(bank) + 15) & ~15 != source
            or not uv_sequences._bank_covers(scores, bank['programs'])
            or not audio._fits(image, dict(bank, corroborated=True), base, [audio.MAX_HEADER_CHECKS], lambda: None)):
        raise formats.AssetError('The Compact MIDI directory changed. Rescan ROM Explorer.')
    return uv_sequences.render_sequence(image, asset, index, bank, base)
