"""Read a bounded first pass of older libmus song tracks."""

import re
import struct
from dataclasses import dataclass

_HEADER = struct.Struct('>6I')
_SIGNATURE = re.compile(rb'\0\0\0[\x02-\x20]\0\0\0\x18')
_WIDTHS = dict.fromkeys((0x82,0x85,0x87,0x8d,0x8f,0x95,0x9b,0x9c,0x9e,0xa0,0xa2,0xa6,0xa8,0xa9), 1)
_WIDTHS.update(dict.fromkeys((0x86,0x9d,0xa3,0xa4,0xa5), 2))
_WIDTHS.update(dict.fromkeys((0x88,0x89,0x97), 3))
_WIDTHS.update(dict.fromkeys((0x83,0x8a,0x8c,0x8e,0x91,0x92,0x93,0x94,0x96,0x99,0x9a,0x9f), 0))
_WIDTHS[0x84] = 7
_MAX_BYTES = 256*1024


@dataclass(frozen=True, slots=True)
class Note:
    tick: int
    duration: int
    key: int
    wave: int
    velocity: int
    pan: int


def _track(data, start, end, waves):
    at = start
    tick = fixed = wave = 0
    velocity = 127
    pan = 64
    explicit_velocity = ignore_fixed = False
    notes, tempos, loops = [], [], []

    def byte():
        nonlocal at
        if at >= end:
            raise ValueError
        value = data[at]
        at += 1
        return value

    def variable():
        hi = byte()
        return ((hi & 127)<<8)|byte() if hi & 128 else hi

    for _ in range(32768):
        cmd = byte()
        if cmd < 128:
            strength = byte() if explicit_velocity else velocity
            length = fixed if fixed and not ignore_fixed else variable()
            ignore_fixed = False
            if cmd != 0x60:
                if cmd > 0x60 or wave not in waves:
                    raise ValueError
                notes.append(Note(tick, length, cmd, wave, strength, pan))
            tick += length
            continue
        if cmd == 0x80:
            return at, notes, tempos, False
        if cmd in (0x81, 0x8b, 0x90, 0xa7):
            value = variable()
            if cmd == 0x81:
                wave = value
            elif cmd == 0x8b:
                fixed = value
            continue
        if cmd not in _WIDTHS:
            raise ValueError
        args = [byte() for _ in range(_WIDTHS[cmd])]
        if cmd == 0x85 and args[0]:
            tempos.append((tick, args[0]))
        elif cmd == 0x8c:
            ignore_fixed = True
        elif cmd == 0x95:
            if len(loops) == 4 or not args[0]:
                raise ValueError
            loops.append((at, args[0]))
        elif cmd == 0x96 and loops:
            target, repeats = loops.pop()
            if repeats == 255:
                return at, notes, tempos, True
            if repeats > 1:
                loops.append((target, repeats-1))
                at = target
        elif cmd == 0x9c:
            pan = args[0]>>1
        elif cmd == 0x99:
            explicit_velocity = True
        elif cmd in (0x9a, 0x9b):
            explicit_velocity = False
            if args:
                velocity = args[0]
    raise ValueError


def song(data, waves):
    if len(data) < _HEADER.size:
        return None
    channels, notes, volume, bend, envelopes, drums = _HEADER.unpack_from(data)
    if (not 2 <= channels <= 32 or notes != _HEADER.size or volume != notes+4*channels
            or bend != volume+4*channels or envelopes != bend+4*channels or drums != envelopes
            or envelopes >= len(data)):
        return None
    tracks = [at for at, in struct.iter_unpack('>I', data[notes:volume]) if at]
    if (len(tracks) < 2 or tracks != sorted(set(tracks)) or tracks[-1] >= len(data)
            or tracks[0] < envelopes or (tracks[0]-envelopes)%7 or any(data[volume:envelopes])):
        return None
    events, tempos, loops, extent = [], [], 0, 0
    try:
        for start, end in zip(tracks, tracks[1:]+[len(data)]):
            extent, voice, tempo, loops_here = _track(data, start, end, waves)
            events.extend(voice)
            tempos.extend(tempo)
            loops += loops_here
    except ValueError:
        return None
    return dict(extent=extent, notes=events, tempos=tempos, loops=loops, channels=len(tracks)) if events else None


def regions(image, banks, *, check=lambda: None):
    resolved = [bank for bank in banks if bank['offset'] == bank['bank_offset'] and bank['samples']]
    if len(resolved) != 1:
        return []
    bank = resolved[0]
    waves = {sample['instrument'] for sample in bank['samples']}
    assets = []
    for match in _SIGNATURE.finditer(image):
        check()
        start = match.start()
        if start%4:
            continue
        if score := song(image[start:start+_MAX_BYTES], waves):
            assets.append(dict(offset=start, size=score['extent'], kind='music sequence', media='metadata',
                               layout='libmus-raw-song', confidence='validated', label='libmus song',
                               channels=score['channels'], notes=len(score['notes']), loops=score['loops'],
                               reason='The raw libmus channel table and timed note commands resolve to a unique wave bank.',
                               preview_settings=dict(format='auto', source='rom', offset=start)))
    return assets


def preview(image, asset, selection):
    return dict(media='metadata', title=asset['label'], fields={'Channels':asset['channels'], 'Notes':asset['notes'],
                'Looping channels':asset['loops']}, settings=asset['preview_settings'])
