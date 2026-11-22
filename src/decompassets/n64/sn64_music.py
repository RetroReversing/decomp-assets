"""Bounded single-pass playback for SSEQ tracks with their SN64 patches."""

import base64
import struct
from collections import defaultdict, deque

from .. import formats
from . import compact_midi, compact_midi_render, sn64, uv_sequences

_TRACK = struct.Struct('>HHHBBHHHHHH')
_LENGTHS = {2: 0, 7: 2, 9: 2, 11: 1, 12: 1, 13: 1, 14: 1, 15: 1, 17: 2, 18: 1, 32: 2, 35: 0}


def programs(image, control, wave, samples):
    head = sn64._HEAD.unpack_from(image, control)
    patches, patch_size, voices, voice_size = head[9:13]
    patch_base = control + sn64._HEAD.size
    voice_start = patch_base + patches * patch_size
    limit = control + sn64._HEAD.size + head[6]
    candidates = []
    for padding in (0, 4):
        base = voice_start + padding
        if base + voices * voice_size > limit:
            continue
        records = [image[base+i*voice_size:base+(i+1)*voice_size] for i in range(voices)]
        if all(r[1] <= 127 and r[2] <= 127 and r[3] in (0, 1) and r[4] <= 127
               and r[6] <= r[7] <= 127 and int.from_bytes(r[10:12], 'big') < len(samples) for r in records):
            candidates.append(base)
    if len(candidates) != 1:
        return None
    voice_base = candidates[0]
    result = {}
    for index in range(patches):
        at = patch_base + index * patch_size
        count = int.from_bytes(image[at:at+2], 'little')
        first = int.from_bytes(image[at+2:at+4], 'big')
        if first + count > voices:
            return None
        entries = []
        for v in range(first, first + count):
            record = image[voice_base+v*voice_size:voice_base+(v+1)*voice_size]
            sample = int.from_bytes(record[10:12], 'big')
            keymin, keymax = record[6:8]
            if sample >= len(samples) or keymin > keymax or keymax > 127:
                continue
            item = dict(samples[sample], relative_offset=samples[sample]['offset'] - wave)
            entries.append(dict(sample=item, velocity_range=(0, 127), key_range=(keymin, keymax),
                                key_base=record[4] - int(item.get('pitch_cents', 0) / 100),
                                detune=record[5] if record[5] < 128 else record[5]-256,
                                volume=record[1]*record[18]/127**2, pan=min(record[2], 127)))
        result[0, index] = entries
    return result


def _variable(data, pos):
    value = 0
    for _ in range(4):
        if pos >= len(data):
            raise ValueError
        byte = data[pos]
        pos += 1
        value = value * 128 + (byte & 127)
        if byte < 128:
            return value, pos
    raise ValueError


def sequence(image, row):
    if not 0 < row['tracks'] <= 16:
        return None
    at, end = row['offset'], row['offset'] + row['size']
    events = []
    tempo = division = None
    try:
        for channel in range(row['tracks']):
            if at + _TRACK.size > end:
                return None
            flag, program, _, volume, pan, _, bpm, ticks, loop, _, length = _TRACK.unpack_from(image, at)
            start = at + _TRACK.size + (4 if loop else 0)
            at = start + length
            if (at > end or not 0 < bpm <= 1000 or not 0 < ticks <= 32767 or volume > 127 or pan > 127
                    or row['tracks'] > 1 and not flag & 0x100):
                return None
            if tempo is None:
                tempo, division = bpm, ticks
            elif (tempo, division) != (bpm, ticks):
                return None
            events.extend((compact_midi.Event(0, 0xc0 | channel, (program,)),
                           compact_midi.Event(0, 0xb0 | channel, (7, volume)),
                           compact_midi.Event(0, 0xb0 | channel, (10, pan))))
            data = image[start:at]
            pos = tick = 0
            active = defaultdict(deque)
            ended = False
            while pos < len(data) and len(events) < 65536:
                delay, pos = _variable(data, pos)
                tick += delay
                if pos >= len(data):
                    return None
                op = data[pos]
                pos += 1
                if op == 0x22:
                    ended = True
                    break
                length = _LENGTHS.get(op)
                if length is None or pos + length > len(data):
                    return None
                args = data[pos:pos+length]
                pos += length
                if op == 7:
                    events.append(compact_midi.Event(tick, 0xc0 | channel, (args[0],)))
                elif op in (12, 13, 14):
                    control = {12: 7, 13: 10, 14: 64}[op]
                    if args[0] > 127:
                        return None
                    events.append(compact_midi.Event(tick, 0xb0 | channel, (control, args[0])))
                elif op == 9:
                    bend = max(0, min(16383, int.from_bytes(args, 'little', signed=True) + 8192))
                    events.append(compact_midi.Event(tick, 0xe0 | channel, (bend & 127, bend >> 7)))
                elif op == 17:
                    if args[0] > 127 or args[1] > 127:
                        return None
                    active[args[0]].append((tick, args[1]))
                elif op == 18:
                    if args[0] > 127:
                        return None
                    if active[args[0]]:
                        begin, velocity = active[args[0]].popleft()
                        if tick > begin:
                            events.append(compact_midi.Event(begin, 0x90 | channel, (args[0], velocity), tick-begin))
            if not ended:
                return None
        if tempo is None:
            return None
        micros = 60_000_000 // tempo
        events.append(compact_midi.Event(0, 0xff, tuple(micros.to_bytes(3, 'big'))))
        events.sort(key=lambda event: event.tick)
        return division, events
    except (IndexError, ValueError, struct.error, OverflowError):
        return None


def music_rows(image, rows, voices):
    result = []
    for index, row in enumerate(rows):
        if not int.from_bytes(image[row['offset']:row['offset']+2], 'big') & 0x100:
            continue
        if not (score := sequence(image, row)):
            continue
        notes = sum(event.status & 0xf0 == 0x90 and event.duration and event.data[1] for event in score[1])
        resolved = list(uv_sequences.note_voices(score[1], voices))
        if (notes and uv_sequences._bank_covers([score[1]], voices)
                and any(voice and voice['gain'] for _, voice in resolved)):
            result.append(dict(offset=row['offset'], size=row['size'], sequence=index,
                               codec='SSEQ', label=f'Sequence {index}', preview_available=True))
    return result


def preview(image, asset, selection):
    index = formats.integer(selection.get('sample', 0), 'Sequence', 0, len(asset['samples'])-1)
    parsed = sn64._samples(image, asset['control'], lambda: None)
    if not parsed:
        raise formats.AssetError('The sound bank changed. Scan ROM Explorer again.')
    _, sequence_at, _, wave, samples, rows = parsed
    voices = programs(image, asset['control'], wave, samples)
    entry = asset['samples'][index]
    seq = entry['sequence']
    if (sequence_at != asset['offset'] or not voices or seq >= len(rows)
            or rows[seq]['offset'] != entry['offset'] or rows[seq]['size'] != entry['size']
            or not (score := sequence(image, rows[seq])) or not uv_sequences._bank_covers([score[1]], voices)):
        raise formats.AssetError('The sequence directory changed. Scan ROM Explorer again.')
    pcm, stats = compact_midi_render.render(image, wave, score[0], score[1], uv_sequences.note_voices(score[1], voices))
    payload, details = formats.pcm(pcm, dict(format='pcm-s16le', channels=2, rate=compact_midi_render.RATE, length=len(pcm)))
    details.update(stats, format='SSEQ', sample=index,
                   note='Single-pass sample-backed preview. Envelopes, held-note bends and repeated loops can differ.')
    return dict(media='audio', mime='audio/wav', details=details,
                data_url='data:audio/wav;base64,' + base64.b64encode(payload).decode(),
                settings=dict(asset['preview_settings'], sample=index))
