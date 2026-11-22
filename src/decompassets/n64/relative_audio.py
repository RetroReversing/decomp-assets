"""Bit-packed B1 sound banks following a relative resource directory."""

import base64

from .. import formats
from . import audio, compact_midi, compact_midi_render, relative_directory, uv_sequences

BANK = 'relative-directory-audio-bank'
SONG = 'relative-directory-song'
_LIMIT = 1024 * 1024


def unpack(image, start, end):
    """Decode the bounded, MSB-first 13-bit-window stream and its terminator."""
    if not 0 <= start < end <= len(image):
        return None
    pos = start * 8
    last = end * 8
    window = bytearray(8192)
    write = 1
    output = bytearray()

    def bits(count):
        nonlocal pos
        if pos + count > last:
            raise ValueError
        value = 0
        for _ in range(count):
            value = (value << 1) | ((image[pos >> 3] >> (7 - (pos & 7))) & 1)
            pos += 1
        return value

    try:
        while len(output) < _LIMIT:
            if bits(1):
                chunk = bytes([bits(8)])
                for value in chunk:
                    output.append(value)
                    window[write] = value
                    write = (write + 1) & 8191
            else:
                source = bits(13)
                if not source:
                    return (bytes(output), (pos + 7) // 8) if output.startswith(b'B1') else None
                count = bits(3) + 3
                if len(output) + count > _LIMIT:
                    return None
                for i in range(count):
                    value = window[(source + i) & 8191]
                    output.append(value)
                    window[write] = value
                    write = (write + 1) & 8191
            if len(output) >= 2 and output[:2] != b'B1':
                return None
    except ValueError:
        return None
    return None


def _bank(image, start, check):
    decoded = unpack(image, start, min(len(image), start + _LIMIT))
    if not decoded:
        return None
    data, packed_end = decoded
    try:
        info = audio.bank(data, 0, check=check)
    except audio.KeyMapError:
        try:
            info = audio.bank(data, 0, sample_only=True, check=check)
        except audio.BankError:
            return None
    except audio.BankError:
        return None
    table = (packed_end + 15) & ~15
    extent = max(sample['relative_offset'] + sample['size'] for sample in info['samples'])
    if table + extent > len(image) or any(image[packed_end:table]):
        return None
    if not audio._fits(image, dict(info, offset=start, size=table-start), table, [audio.MAX_HEADER_CHECKS], check):
        return None
    return data, info, table, (table + extent + 15) & ~15


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for base, tables in relative_directory.tables(image, check=check):
        directory_end = max(base + (table[-1] & 0x7fffffff) for table in tables if table)
        for start in range((directory_end + 15) & ~15, min(len(image), directory_end + 256), 16):
            check()
            first = _bank(image, start, check)
            if not first:
                continue
            music = first
            music_control = start
            while first:
                _, info, table, following = first
                samples = [dict(sample, offset=table + sample['relative_offset']) for sample in info['samples']]
                result.append(dict(offset=start, size=table-start, table_offset=table, directory=base,
                                   kind='audio', media='audio', audio_kind='sample bank', layout=BANK,
                                   samples=samples, confidence='validated',
                                   label=f'{len(samples)} instrument and effect samples',
                                   reason='The compressed control graph and every ADPCM frame validate against the adjacent sample table.',
                                   preview_settings=dict(format='auto', source='rom', offset=start)))
                start = following
                first = _bank(image, start, check)
            _, bank, table, _ = music
            for index, (a, b) in enumerate(zip(tables[0], tables[0][1:])):
                if index % 16 == 0:
                    check()
                lo, hi = base + (a & 0x7fffffff), base + (b & 0x7fffffff)
                if a & 0x80000000 or not (data := relative_directory.unpack(image, lo, hi)):
                    continue
                score = compact_midi.sequence(data)
                if not score or not uv_sequences._bank_covers([score[1]], bank['programs']):
                    continue
                notes = sum(event.status & 0xf0 == 0x90 and event.duration > 0 and event.data[1] > 0
                            for event in score[1])
                result.append(dict(offset=lo, size=hi-lo, kind='music sequence', media='audio',
                                   audio_kind='indexed sample directory', layout=SONG, confidence='validated',
                                   label=f'Music sequence {index}', control=music_control,
                                   table_offset=table, directory=base,
                                   samples=[dict(offset=lo, size=hi-lo, codec='Nintendo compact MIDI',
                                                 label=f'Sequence {index}', preview_available=bool(notes))],
                                   reason='The directory bounds a complete compact MIDI sequence and the instrument bank resolves its notes.',
                                   preview_settings=dict(format='auto', source='rom', offset=lo)))
            break
    return result


def preview(image, asset, selection):
    if asset['layout'] == SONG:
        formats.integer(selection.get('sample', 0), 'Sequence', 0, 0)
        found = _bank(image, asset['control'], lambda: None)
        data = relative_directory.unpack(image, asset['offset'], asset['offset'] + asset['size'])
        score = compact_midi.sequence(data) if data else None
        if not found or found[2] != asset['table_offset'] or not score:
            raise formats.AssetError('The compressed song or its bank changed. Scan ROM Explorer again.')
        control, bank, table, _ = found
        division, events = score
        if not uv_sequences._bank_covers([events], bank['programs']):
            raise formats.AssetError('The song no longer matches its instrument bank. Scan ROM Explorer again.')
        pcm, stats = compact_midi_render.render(image, table, division, events,
                                                uv_sequences.note_voices(events, bank['programs']), book_image=control)
        payload, details = formats.pcm(pcm, dict(format='pcm-s16le', channels=2,
                                                  rate=compact_midi_render.RATE, length=len(pcm)))
        details.update(stats, format='Nintendo compact MIDI', sample=0,
                       note='Single-pass sample-backed preview. Envelopes and held-note bends can differ.')
        return dict(media='audio', mime='audio/wav', details=details,
                    data_url='data:audio/wav;base64,' + base64.b64encode(payload).decode(),
                    settings=dict(asset['preview_settings'], sample=0))
    found = _bank(image, asset['offset'], lambda: None)
    if not found or found[2] != asset['table_offset']:
        raise formats.AssetError('The compressed sound bank changed. Scan ROM Explorer again.')
    return audio.preview(image, asset, selection, book_image=found[0])
