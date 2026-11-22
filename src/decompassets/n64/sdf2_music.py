"""Timed SDF2 music streams and their sample-backed instruments."""

import base64
import struct
from collections import defaultdict, deque
from dataclasses import replace

from .. import formats
from . import compact_midi, compact_midi_render, sdf2_audio, uv_sequences
from .compact_midi import Event

LAYOUT = 'sdf2-music'
_MAX_SEQUENCE = 256*1024


def _score(data):
    # The stream uses compact MIDI backreferences, but conventional note-off
    # events and running status across tempo changes rather than note lengths.
    track = compact_midi._Track(bytes(68)+data, 68, 68+len(data))
    pending = defaultdict(deque)
    events = []
    tick = running = 0
    try:
        for _ in range(compact_midi._MAX_EVENTS):
            tick += track.variable()
            first = track.byte()
            if first == 0xff:
                kind = track.byte()
                if kind == 0x2f:
                    return track.at-68, events
                if kind == 0x51:
                    tempo = tuple(track.byte() for _ in range(3))
                    if not any(tempo):
                        return None
                    events.append(Event(tick, 0xff, tempo))
                elif kind == 0x2e:
                    track.byte()
                    if track.byte() != 0xff:
                        return None
                elif kind == 0x2d:
                    track.byte()
                    track.byte()
                    for _ in range(4):
                        track.byte(compressed=False)
                else:
                    return None
                continue
            if first >= 128:
                running, fields = first, ()
            else:
                fields = (first,)
            command = running & 0xf0
            if command not in compact_midi._LENGTH:
                return None
            fields += tuple(track.byte() for _ in range(compact_midi._LENGTH[command]-len(fields)))
            if any(value >= 128 for value in fields):
                return None
            if command in (0x80, 0x90):
                key = running & 15, fields[0]
                if command == 0x90 and fields[1]:
                    pending[key].append(len(events))
                    events.append(Event(tick, running, fields))
                elif pending[key]:
                    index = pending[key].popleft()
                    events[index] = replace(events[index], duration=tick-events[index].tick)
            else:
                events.append(Event(tick, running, fields))
    except (ValueError, IndexError, struct.error):
        return None
    return None


def _directory(image, start, table_size, samples, check):
    end = start+table_size
    pos = start+16+len(samples)*24
    if pos+4 > end:
        return None
    count, = struct.unpack_from('>I', image, pos)
    pos += 4
    if not 1 <= count <= 128 or pos+count*12+4 > end:
        return None
    programs = {}
    for index in range(count):
        check()
        zones, pointer, number = struct.unpack_from('>3I', image, pos+12*index)
        if not 1 <= zones <= 128 or number > 127 or (0, number) in programs or not 0 <= pointer <= table_size-zones*12:
            return None
        voices = []
        for zone in range(zones):
            definition, envelope, sample_index = struct.unpack_from('>3I', image, start+pointer+12*zone)
            if not 0 <= definition <= table_size-8 or not 0 <= envelope <= table_size-8 or sample_index >= len(samples):
                return None
            velocity_min, velocity_max, key_min, key_max, root, detune, _, _ = image[start+definition:start+definition+8]
            if not 0 <= velocity_min <= velocity_max <= 127 or not 0 <= key_min <= key_max <= 127 or root > 127:
                return None
            sample = dict(samples[sample_index], relative_offset=samples[sample_index]['offset'])
            loop = sample.get('loop')
            if loop and loop['end'] <= sample['samples']:
                sample['loop'] = dict(loop, count=999)
            else:
                sample.pop('loop', None)
            voices.append(dict(sample=sample, key_range=(key_min, key_max), velocity_range=(velocity_min, velocity_max),
                               key_base=root, detune=(detune if detune < 128 else detune-256)*100/256,
                               volume=1, pan=64))
        programs[(0, number)] = voices
    if (0, 31) in programs:
        programs[(0, 'percussion')] = programs[(0, 31)]
    pos += count*12
    number, = struct.unpack_from('>I', image, pos)
    pos += 4
    if not 2 <= number <= 128 or pos+8*number > end:
        return None
    rows = list(struct.iter_unpack('>2I', image[pos:pos+8*number]))
    first_expected = samples[-1]['offset']+samples[-1]['size']-start
    if rows[0][1] != first_expected or any(not 1 <= division <= 32767 for division, _ in rows):
        return None
    if any(a[1] >= b[1] for a, b in zip(rows, rows[1:])):
        return None
    sequences = []
    for index, (division, relative) in enumerate(rows):
        check()
        begin = start+relative
        limit = start+rows[index+1][1] if index+1 < len(rows) else min(len(image), begin+_MAX_SEQUENCE)
        if not 0 <= begin < limit <= len(image) or limit-begin > _MAX_SEQUENCE:
            return None
        score = _score(image[begin:limit])
        if not score:
            return None
        used, events = score
        if not events or index+1 < len(rows) and (limit-begin-used > 1 or any(image[begin+used:limit])):
            return None
        sequences.append(dict(offset=begin, size=used, division=division, notes=sum(e.status&0xf0 == 0x90 for e in events)))
    return programs, sequences


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for match in sdf2_audio._HEADER.finditer(image):
        start = match.start()
        if start%4 or not (bank := sdf2_audio._bank(image, start, check)):
            continue
        table_size, samples = bank
        directory = _directory(image, start, table_size, samples, check)
        if not directory:
            continue
        _, rows = directory
        for index, row in enumerate(rows):
            result.append(dict(offset=row['offset'], size=row['size'], kind='music sequence', media='audio',
                               audio_kind='indexed sample directory', layout=LAYOUT, confidence='validated',
                               label=f'SDF2 song {index+1}', bank_offset=start, index=index, notes=row['notes'],
                               samples=[dict(offset=row['offset'], size=row['size'], codec='SDF2 MIDI',
                                             label=f'Song {index+1}', preview_available=True)],
                               reason='The song directory, timed events, instrument zones and ADPCM bank agree.',
                               preview_settings=dict(source='rom', format='auto', offset=row['offset'])))
    return result


def preview(image, asset, selection):
    formats.integer(selection.get('sample', 0), 'Sequence', 0, 0)
    start = asset['bank_offset']
    bank = sdf2_audio._bank(image, start, lambda: None)
    directory = _directory(image, start, *bank, lambda: None) if bank else None
    index = asset['index']
    if not directory or not 0 <= index < len(directory[1]):
        raise formats.AssetError('The SDF2 music directory changed. Rescan ROM Explorer.')
    programs, rows = directory
    row = rows[index]
    if (row['offset'], row['size']) != (asset['offset'], asset['size']):
        raise formats.AssetError('The SDF2 song changed. Rescan ROM Explorer.')
    score = _score(image[row['offset']:row['offset']+row['size']])
    if not score:
        raise formats.AssetError('The SDF2 song changed. Rescan ROM Explorer.')
    _, events = score
    voices = list(uv_sequences.note_voices(events, programs))
    pcm, stats = compact_midi_render.render(image, 0, row['division'], events, voices, label='SDF2 music')
    payload, details = formats.pcm(pcm, dict(format='pcm-s16le', channels=2,
                                              rate=compact_midi_render.RATE, length=len(pcm)))
    details.update(stats, format='SDF2 MIDI', sample=0,
                   note='Single-pass sample-backed preview. Envelopes, tuning and held-note bends can differ.')
    return dict(media='audio', mime='audio/wav', details=details,
                data_url='data:audio/wav;base64,'+base64.b64encode(payload).decode(),
                settings=dict(asset['preview_settings'], sample=0))
