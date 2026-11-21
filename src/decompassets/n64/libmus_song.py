"""Read and preview a bounded first pass of older libmus song tracks."""

import base64
import re
import struct
from dataclasses import dataclass

from .. import formats
from . import audio, compact_midi_render, ptr_audio
from .compact_midi import Event

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
    volume: int


def _signed(byte):
    return (byte+128)%256-128


def _track(data, start, end, waves):
    at = start
    tick = fixed = wave = 0
    transpose = cutoff = endit = 0
    velocity = volume = 127
    pan = 64
    explicit_velocity = ignore_fixed = ignore_transpose = False
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
                key = cmd if ignore_transpose else cmd + transpose
                ignore_transpose = False
                duration = min(length, cutoff) if cutoff else max(0, length-endit)
                notes.append(Note(tick, duration, key, wave, strength, pan, volume))
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
        elif cmd == 0x86:
            cutoff, endit = int.from_bytes(bytes(args), 'big'), 0
        elif cmd == 0x87:
            cutoff, endit = 0, args[0]
        elif cmd == 0x8d:
            transpose = _signed(args[0])
        elif cmd == 0x8e:
            ignore_transpose = True
        elif cmd == 0xa6:
            volume = args[0]
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
            assets.append(dict(offset=start, size=score['extent'], kind='music sequence', media='audio',
                               audio_kind='indexed sample directory', control=bank['offset'],
                               table_offset=bank['table_offset'],
                               samples=[dict(offset=start, size=score['extent'], codec='Nintendo libmus',
                                             label='Song', preview_available=True)],
                               layout='libmus-raw-song', confidence='validated', label='libmus song',
                               channels=score['channels'], notes=len(score['notes']), loops=score['loops'],
                               reason='The raw libmus channel table and timed note commands resolve to a unique wave bank.',
                               preview_settings=dict(format='auto', source='rom', offset=start)))
    return assets


def preview(image, asset, selection):
    if 'sample' in selection:
        return _play(image, asset, selection)
    return dict(media='metadata', title=asset['label'], fields={'Channels':asset['channels'], 'Notes':asset['notes'],
                'Looping channels':asset['loops']}, settings=asset['preview_settings'])


def _play(image, asset, selection):
    index = formats.integer(selection['sample'], 'Sequence', 0, 0)
    base = asset['table_offset']
    try:
        bank = ptr_audio.bank(image, asset['control'])
    except audio.BankError as exc:
        raise formats.AssetError('The libmus wave bank changed. Rescan ROM Explorer.') from exc
    if (image[base:base+len(ptr_audio.WAVES)] != ptr_audio.WAVES
            or not ptr_audio.fits(image, bank, base, [ptr_audio.MAX_FRAME_CHECKS], lambda: None)):
        raise formats.AssetError('The libmus wave table failed sample validation. Rescan ROM Explorer.')
    waves = {sample['instrument']:sample for sample in bank['samples']}
    start, size = asset['offset'], asset['size']
    score = song(image[start:start+size], waves) if 0 <= start < start+size <= len(image) else None
    if score is None:
        raise formats.AssetError('The libmus channel data changed. Rescan ROM Explorer.')

    tempos = [Event(tick, 0xff, tuple((60_000_000//bpm).to_bytes(4, 'big')))
              for tick, bpm in score['tempos']]
    voices = []
    for note in score['notes']:
        sample = waves[note.wave]
        pitch = note.key + _signed(sample['base_note_byte']-48) + sample['detune']/100
        gain = (note.volume*note.velocity/127**2)**2 if pitch <= 12 else 0
        voices.append((note, dict(sample=sample, pitch=pitch, pan=note.pan, gain=gain)))
    pcm, stats = compact_midi_render.render(image, base, 48, tempos, voices, label='libmus')
    payload, details = formats.pcm(pcm, dict(format='pcm-s16le', channels=2,
                                           rate=compact_midi_render.RATE, length=len(pcm)))
    details.update(stats, format='Nintendo libmus', sample=index,
                   note='Single-pass sample-backed preview. Envelopes, ties and modulation can differ.')
    return dict(media='audio', mime='audio/wav', details=details,
                data_url='data:audio/wav;base64,'+base64.b64encode(payload).decode(),
                settings={**asset['preview_settings'], 'sample':index})
