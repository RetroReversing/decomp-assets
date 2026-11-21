"""Validate UVMS music directories and their compact MIDI sequences."""

import base64
import re
import struct
from itertools import islice

from .. import formats
from . import audio, compact_midi, compact_midi_render

_ENTRY = struct.Struct('>II')


def directories(image, *, check=lambda: None):
    for match in islice(re.finditer(rb'FORM.{4}UVMS', image, re.S), 128):
        offset = match.start()
        end = offset+8+int.from_bytes(image[offset+4:offset+8], 'big')
        if offset%2 or not offset+12 <= end <= len(image):
            continue
        at = offset+12
        for _ in range(16):
            if at+8 > end:
                break
            tag, size = struct.unpack_from('>4sI', image, at)
            start = at+8
            at = start+size
            if at > end:
                break
            if tag == b'PAD ':
                continue
            if tag == b'SEQS' and at == end:
                rows = _entries(image, start, end, check)
                if rows:
                    yield offset, end, rows
            break


def _entries(image, start, end, check, *, exact=True):
    if end-start < 4 or image[start:start+2] != b'S1':
        return None
    count = int.from_bytes(image[start+2:start+4], 'big')
    cursor = 4+count*_ENTRY.size
    if not 1 <= count <= 128 or cursor > end-start:
        return None
    rows = []
    for i in range(count):
        check()
        offset, length = _ENTRY.unpack_from(image, start+4+i*_ENTRY.size)
        first, last = start+offset, start+offset+length
        if offset != cursor or not 0 < length <= 256*1024 or last > end:
            return None
        score = compact_midi.sequence(image[first:last])
        if score is None:
            return None
        division, events = score
        notes = sum(event.status & 0xf0 == 0x90 and event.duration > 0 and event.data[1] > 0 for event in events)
        rows.append(dict(offset=first, size=length, division=division, notes=notes))
        cursor = (offset+length+3)&~3
    if not exact:
        return rows if start+cursor <= end else None
    return rows if 0 <= end-start-cursor < 16 and not any(image[start+cursor:end]) else None


def _sample_end(samples, base):
    return max(base+s['relative_offset']+s['size'] for s in samples)


def _asset(offset, end, rows, label, reason, control=None):
    asset = dict(offset=offset, size=end-offset, label=label, kind='music sequence',
                 media='metadata', layout='uv-sequence-directory', confidence='validated', sequences=rows,
                 reason=reason, preview_settings=dict(format='auto', source='rom', offset=offset))
    if control is not None:
        asset.update(media='audio', audio_kind='indexed sample directory', control=control,
                     samples=[dict(offset=row['offset'], size=row['size'], codec='Nintendo compact MIDI',
                                   label=f'Sequence {i}', preview_available=bool(row['notes']))
                              for i, row in enumerate(rows)])
    return asset


def regions(image, *, check=lambda: None, progress=lambda _: None, sound_banks=()):
    banks = audio._uv_tables(image, check)
    result = []
    for offset, end, rows in directories(image, check=check):
        music = [control for control, (_, _, wave_end, tag, bank_start) in banks.items()
                 if tag == b'UVMB' and (wave_end == offset or bank_start == end)]
        result.append(_asset(offset, end, rows, 'UV music directory',
                             'The indexed sequences fit the named ROM chunk and decode as compact MIDI.',
                             music[0] if len(music) == 1 else None))
    found = set()
    for bank in sound_banks:
        base = bank.get('table_offset')
        samples = bank.get('samples', [])
        control = bank['offset']
        if (bank.get('audio_kind') != 'sample bank' or base is None or not samples
                or control in banks or image[control:control+2] != b'B1'
                or base != (control+bank['size']+15)&~15):
            continue
        tail = _sample_end(samples, base)
        offset = (tail+3)&~3
        if offset in found or any(image[tail:offset]):
            continue
        rows = _entries(image, offset, len(image), check, exact=False)
        if rows:
            found.add(offset)
            end = (rows[-1]['offset']+rows[-1]['size']+3)&~3
            asset = _asset(offset, end, rows, 'Compact MIDI music directory',
                           'A complete S1 directory follows the validated adjacent sample table.',
                           control)
            result.append({**asset, 'table_offset':base})
    return result


def preview(image, asset, selection):
    from .resource_inspection import table

    rows = asset['sequences']
    if 'sample' in selection and 'control' in asset:
        return _play(image, asset, selection)
    return dict(media='metadata', title=asset['label'], fields={'Sequencer': 'Nintendo compact MIDI'},
                table=table(asset['label'], ['index', 'offset', 'size', 'division', 'notes'], len(rows),
                            rows.__getitem__, selection),
                settings=asset['preview_settings'])


def note_voices(events, programs, bank=0):
    """Resolve Compact MIDI notes in event order with per-channel controls."""
    program, volume, expression, pan, bend = ([0]*16, [127]*16, [127]*16, [64]*16, [8192]*16)
    for event in events:
        channel, command = event.status & 15, event.status & 0xf0
        if command == 0xc0:
            program[channel] = event.data[0]
        elif command == 0xb0:
            control, value = event.data
            if control == 7:
                volume[channel] = value
            elif control == 10:
                pan[channel] = value
            elif control == 11:
                expression[channel] = value
        elif command == 0xe0:
            low, high = event.data
            bend[channel] = low+128*high
        elif command == 0x90 and event.duration and event.data[1]:
            key, velocity = event.data
            index = 'percussion' if channel == 9 and (bank, 'percussion') in programs else program[channel]
            voice = next((voice for voice in programs.get((bank, index), ())
                          if voice['key_range'][0] <= key <= voice['key_range'][1]
                          and voice['velocity_range'][0] <= velocity <= voice['velocity_range'][1]), None)
            if voice is None:
                yield event, None
                continue
            pitch = key-voice['key_base']+voice['detune']/100+2*(bend[channel]-8192)/8192
            gain = voice['volume']*velocity*volume[channel]*expression[channel]/127**3
            stereo = max(0, min(127, voice['pan']+pan[channel]-64))
            yield event, dict(sample=voice['sample'], pitch=pitch, gain=gain, pan=stereo)



def _play(image, asset, selection):
    index = formats.integer(selection['sample'], 'Sequence', 0, len(asset['sequences'])-1)
    control = asset['control']
    try:
        bank = audio.bank(image, control)
    except audio.BankError as exc:
        raise formats.AssetError('The music bank is invalid. Rescan ROM Explorer.') from exc
    if 'table_offset' in asset:
        base = asset['table_offset']
        tail = _sample_end(bank['samples'], base)
        if (base != (control+bank['size']+15)&~15 or (tail+3)&~3 != asset['offset']
                or any(image[tail:asset['offset']]) or image[asset['offset']:asset['offset']+2] != b'S1'):
            raise formats.AssetError('The music bank no longer meets the S1 directory. Rescan ROM Explorer.')
    else:
        bounds = audio._uv_tables(image, lambda: None).get(control)
        if not bounds:
            raise formats.AssetError('The UV music bank changed. Rescan ROM Explorer.')
        control_end, base, wave_end, tag, bank_start = bounds
        if (tag != b'UVMB' or control+bank['size'] > control_end
                or (wave_end != asset['offset'] and bank_start != asset['offset']+asset['size'])
                or _sample_end(bank['samples'], base) > wave_end):
            raise formats.AssetError('The UV music bank exceeds its named chunks. Rescan ROM Explorer.')
        bank['corroborated'] = True
    if not audio._fits(image, bank, base, [audio.MAX_HEADER_CHECKS], lambda: None):
        raise formats.AssetError('The UV music bank failed sample validation. Rescan ROM Explorer.')
    return render_sequence(image, asset, index, bank, base)


def render_sequence(image, asset, index, bank, base, *, book_image=None):
    row = asset['sequences'][index]
    start, size = row['offset'], row['size']
    end = asset['offset']+asset['size']
    score = compact_midi.sequence(image[start:start+size]) if asset['offset'] < start < start+size <= end <= len(image) else None
    if score is None:
        raise formats.AssetError('The compact MIDI sequence changed. Rescan ROM Explorer.')
    division, events = score
    pcm, stats = compact_midi_render.render(image, base, division, events, note_voices(events, bank['programs']),
                                            book_image=book_image)
    payload, details = formats.pcm(pcm, dict(format='pcm-s16le', channels=2,
                                              rate=compact_midi_render.RATE, length=len(pcm)))
    details.update(stats, format='Nintendo compact MIDI', sample=index,
                   note='Single-pass sample-backed preview. Envelopes and bends during held notes can differ.')
    return dict(media='audio', mime='audio/wav', details=details,
                data_url='data:audio/wav;base64,'+base64.b64encode(payload).decode(),
                settings={**asset['preview_settings'], 'sample':index})
