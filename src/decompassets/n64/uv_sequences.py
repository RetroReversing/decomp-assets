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
        if offset%4 or not offset+12 <= end <= len(image):
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


def _entries(image, start, end, check):
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
    return rows if 0 <= end-start-cursor < 16 and not any(image[start+cursor:end]) else None


def regions(image, *, check=lambda: None, progress=lambda _: None):
    banks = audio._uv_tables(image, check)
    result = []
    for offset, end, rows in directories(image, check=check):
        music = [control for control, (_, _, wave_end, tag) in banks.items()
                 if wave_end == offset and tag == b'UVMB']
        asset = dict(offset=offset, size=end-offset, label='UV music directory', kind='music sequence',
                     media='metadata', layout='uv-sequence-directory', confidence='validated', sequences=rows,
                     reason='The indexed sequences fit the named ROM chunk and decode as compact MIDI.',
                     preview_settings=dict(format='auto', source='rom', offset=offset))
        if len(music) == 1:
            asset.update(media='audio', audio_kind='indexed sample directory', control=music[0],
                         samples=[dict(offset=row['offset'], size=row['size'], codec='Nintendo compact MIDI',
                                       label=f'Sequence {i}', preview_available=bool(row['notes']))
                                  for i, row in enumerate(rows)])
        result.append(asset)
    return result


def preview(image, asset, selection):
    from .resource_inspection import table

    rows = asset['sequences']
    if 'sample' in selection and 'control' in asset:
        return _play(image, asset, selection)
    return dict(media='metadata', title=asset['label'], fields={'Sequencer': 'Nintendo compact MIDI'},
                table=table(asset['label'], ['index', 'offset', 'size', 'division', 'notes'], len(rows),
                            lambda i: dict(index=i, **rows[i]), selection),
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
    bounds = audio._uv_tables(image, lambda: None).get(control)
    if not bounds:
        raise formats.AssetError('The UV music bank changed. Rescan ROM Explorer.')
    control_end, base, wave_end, tag = bounds
    try:
        bank = audio.bank(image, control)
    except audio.BankError as exc:
        raise formats.AssetError('The UV music bank is invalid. Rescan ROM Explorer.') from exc
    if (tag != b'UVMB' or control+bank['size'] > control_end or wave_end != asset['offset']
            or any(sample['relative_offset']+sample['size'] > wave_end-base for sample in bank['samples'])):
        raise formats.AssetError('The UV music bank exceeds its named chunks. Rescan ROM Explorer.')
    bank['corroborated'] = True
    if not audio._fits(image, bank, base, [audio.MAX_HEADER_CHECKS], lambda: None):
        raise formats.AssetError('The UV music bank failed sample validation. Rescan ROM Explorer.')
    row = asset['sequences'][index]
    start, size = row['offset'], row['size']
    end = asset['offset']+asset['size']
    score = compact_midi.sequence(image[start:start+size]) if asset['offset'] < start < start+size <= end <= len(image) else None
    if score is None:
        raise formats.AssetError('The compact MIDI sequence changed. Rescan ROM Explorer.')
    division, events = score
    pcm, stats = compact_midi_render.render(image, base, division, events, note_voices(events, bank['programs']))
    payload, details = formats.pcm(pcm, dict(format='pcm-s16le', channels=2,
                                              rate=compact_midi_render.RATE, length=len(pcm)))
    details.update(stats, format='Nintendo compact MIDI', sample=index,
                   note='Single-pass sample-backed preview. Envelopes and bends during held notes can differ.')
    return dict(media='audio', mime='audio/wav', details=details,
                data_url='data:audio/wav;base64,'+base64.b64encode(payload).decode(),
                settings={**asset['preview_settings'], 'sample':index})
