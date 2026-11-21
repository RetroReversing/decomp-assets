"""S1 directories whose entries are LZ-packed format-zero MIDI files."""

import base64
import struct

from .. import formats
from . import audio, compact_midi_render, lz_texture_directories, standard_midi, uv_sequences

LAYOUT = 'n64-lz-standard-midi'
_ROW = struct.Struct('>II')


def _score(image, offset, size, check):
    if not 0 < size <= 256*1024 or offset + size > len(image):
        return None
    try:
        decoded, used = lz_texture_directories.unpack(image[offset:offset+size], check)
    except formats.AssetError:
        return None
    return standard_midi.sequence(decoded) if used == size else None


def _directory(image, offset, check):
    if image[offset:offset+2] != b'S1' or offset+4 > len(image):
        return []
    count = int.from_bytes(image[offset+2:offset+4], 'big')
    cursor = 4 + count*_ROW.size
    if not 1 <= count <= 128 or offset+cursor > len(image):
        return []
    rows = []
    for i in range(count):
        check()
        relative, size = _ROW.unpack_from(image, offset+4+i*_ROW.size)
        start = offset+relative
        if relative != cursor or not (score := _score(image, start, size, check)):
            return []
        division, events = score
        notes = sum(e.status & 0xf0 == 0x90 and e.duration > 0 and e.data[1] > 0 for e in events)
        if not notes:
            return []
        rows.append(dict(label=f'Song {i+1}', offset=start, size=size, division=division,
                         codec='Standard MIDI', preview_available=True))
        cursor = (relative+size+3)&~3
    return rows


def regions(image, *, sound_banks=(), check=lambda: None, progress=lambda _: None):
    found = []
    for bank in sound_banks:
        check()
        control = bank['offset']
        base = bank.get('table_offset')
        samples = bank.get('samples', [])
        if base is None or len(samples) < 2 or image[control:control+2] != b'B1':
            continue
        end = uv_sequences._sample_end(samples, base)
        offset = (end+15)&~15
        if (base != (control+bank['size']+15)&~15 or not (rows := _directory(image, offset, check))):
            continue
        found.append(dict(offset=offset, size=rows[-1]['offset']+rows[-1]['size']-offset,
                          kind='music sequence', media='audio', audio_kind='indexed sample directory',
                          layout=LAYOUT, label='Compressed MIDI songs', confidence='validated', control=control,
                          table_offset=base, samples=rows, preview_settings=dict(source='rom', format='auto',
                                                                               offset=offset),
                          reason='The S1 entries expand to complete Standard MIDI tracks after the validated wave table.'))
    return found


def preview(image, asset, selection):
    rows = asset['samples']
    index = formats.integer(selection.get('sample', 0), 'Song', 0, len(rows)-1)
    row = rows[index]
    score = _score(image, row['offset'], row['size'], lambda: None)
    control, base = asset['control'], asset['table_offset']
    try:
        bank = audio.bank(image, control)
    except audio.BankError as exc:
        raise formats.AssetError('The song wave bank changed. Rescan ROM Explorer.') from exc
    if (score is None or base != (control+bank['size']+15)&~15
            or (uv_sequences._sample_end(bank['samples'], base)+15)&~15 != asset['offset']
            or not audio._fits(image, bank, base, [audio.MAX_HEADER_CHECKS], lambda: None)):
        raise formats.AssetError('The song directory or wave bank changed. Rescan ROM Explorer.')
    division, events = score
    pcm, stats = compact_midi_render.render(image, base, division, events,
                                            uv_sequences.note_voices(events, bank['programs']), label='Standard MIDI')
    payload, details = formats.pcm(pcm, dict(format='pcm-s16le', channels=2, rate=compact_midi_render.RATE,
                                             length=len(pcm)))
    details.update(stats, format='Standard MIDI', sample=index,
                   note='Single-pass sample-backed preview. Envelopes and bends during held notes can differ.')
    return dict(media='audio', mime='audio/wav', details=details,
                data_url='data:audio/wav;base64,'+base64.b64encode(payload).decode(),
                settings={**asset['preview_settings'], 'sample':index})
