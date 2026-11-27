"""Bounded MIDx sequences in RefPack streams, with a clearly synthetic pitch preview."""
import base64
import math
import struct

from .. import formats, refpack

LAYOUT = 'refpack-midx'
RATE = 16000
MAX_EVENTS = 65536
MAX_SECONDS = 12


def sequence(data):
    """Read complete fixed-time MIDI events; unknown opcodes and truncated scores stay unclassified."""
    if len(data) < 8 or data[:4] != b'MIDx' or len(data) > 256*1024:
        return None
    at = 4
    tick = 0
    events = []
    notes = 0
    while at+2 <= len(data) and len(events) < MAX_EVENTS:
        tick += data[at] & 0x7f
        status = data[at+1]
        at += 2
        if status >= 0xf0:
            if at >= len(data):
                return None
            kind = data[at]
            at += 1
            if kind == 0x2f:
                return (events, tick, notes) if notes and not any(data[at:]) else None
            lengths = {0xf8:0, 0x51:3, 0x2d:6, 0x2e:2}
            if kind not in lengths or at+lengths[kind] > len(data):
                return None
            if kind == 0x51:
                tempo = int.from_bytes(data[at:at+3], 'big')
                if not 10000 <= tempo <= 10000000:
                    return None
                events.append((tick, 'tempo', tempo))
            at += lengths[kind]
            continue
        kind = status >> 4
        if not 8 <= kind <= 14:
            return None
        size = 1 if kind in (12, 13) else 2
        if at+size > len(data) or any(x >= 128 for x in data[at:at+size]):
            return None
        if kind in (8, 9):
            note, velocity = data[at:at+2]
            events.append((tick, status, note, velocity))
            notes += kind == 9 and velocity > 0
        at += size
    return None


def regions(image, *, check=lambda: None, **kwargs):
    found = []
    at = 0
    while (at := image.find(b'\x10\xfb', at)) >= 0:
        start = at
        at += 2
        check()
        try:
            data, used = refpack.unpack(memoryview(image)[start:])
        except (ValueError, IndexError):
            continue
        parsed = sequence(data)
        if not parsed:
            continue
        _, ticks, notes = parsed
        found.append(dict(offset=start, size=used, kind='music sequence', media='audio',
                          audio_kind='indexed sample directory', layout=LAYOUT, confidence='validated',
                          label='MIDx music sequence', notes=notes, ticks=ticks,
                          samples=[dict(offset=start, size=used, codec='MIDx', label='Sequence', preview_available=True)],
                          reason='A complete RefPack stream contains bounded timed MIDI events and an end marker.',
                          preview_settings=dict(source='rom', format='auto', offset=start)))
    return found


def _render(events, final_tick):
    """Sine tones expose pitches and timing without pretending to be the game's instruments."""
    active = {}
    intervals = []
    seconds = 0.0
    prior = 0
    tempo = 500000
    for event in events:
        tick = event[0]
        seconds += (tick-prior)*tempo/(480*1000000)
        prior = tick
        if seconds >= MAX_SECONDS:
            break
        if event[1] == 'tempo':
            tempo = event[2]
            continue
        _, status, note, velocity = event
        key = (status & 15, note)
        if key in active:
            begin, vol = active.pop(key)
            intervals.append((begin, seconds, note, vol))
        if status >> 4 == 9 and velocity:
            active[key] = (seconds, velocity)
    else:
        seconds += max(0, final_tick-prior)*tempo/(480*1000000)
    end = min(MAX_SECONDS, max(.1, seconds))
    intervals.extend((begin, end, note, vol) for (_, note), (begin, vol) in active.items())
    samples = [0.0] * int(end*RATE)
    budget = 4_000_000  # Bound work even for deliberately dense or malicious scores.
    for begin, stop, note, velocity in intervals:
        first = max(0, int(begin*RATE))
        last = min(len(samples), int(stop*RATE))
        if last-first > budget:
            break
        budget -= last-first
        frequency = 440*2**((note-69)/12)
        for index in range(first, last):
            envelope = min(1.0, (index-first)/160, (last-index)/160)
            samples[index] += math.sin(2*math.pi*frequency*(index-first)/RATE)*velocity/127*envelope
    return b''.join(struct.pack('<h', int(max(-1, min(1, sample*.08))*32767)) for sample in samples)


def preview(image, asset, selection):
    formats.integer(selection.get('sample', 0), 'Sequence', 0, 0)
    try:
        data, used = refpack.unpack(memoryview(image)[asset['offset']:])
    except (ValueError, IndexError) as exc:
        raise formats.AssetError('The music sequence changed. Rescan ROM Explorer.') from exc
    parsed = sequence(data)
    if not parsed or used != asset['size']:
        raise formats.AssetError('The music sequence changed. Rescan ROM Explorer.')
    events, ticks, notes = parsed
    raw = _render(events, ticks)
    payload, details = formats.pcm(raw, dict(format='pcm-s16le', channels=1, rate=RATE, length=len(raw)))
    details.update(format='MIDx sequence', notes=notes, sample=0,
                   note='Synthetic sine tones show the notes and timing; the game’s instruments are not decoded. '
                        'Tempo defaults to 120 BPM when the sequence does not provide one; '
                        'preview is limited to 12 seconds and dense arrangements may omit notes.')
    return dict(media='audio', mime='audio/wav', details=details,
                data_url='data:audio/wav;base64,'+base64.b64encode(payload).decode(),
                settings=dict(asset['preview_settings'], sample=0))
