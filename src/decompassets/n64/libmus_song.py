"""Read and preview a bounded first pass of older libmus song tracks."""

import base64
import math
import re
import struct
from dataclasses import dataclass, replace

from .. import formats, rnc
from . import audio, compact_midi_render, lzari, ptr_audio, raw_deflate_lists
from .compact_midi import Event

_HEADER = struct.Struct('>6I')
_SIGNATURE = re.compile(rb'\0\0\0[\x02-\x20]\0\0\0\x18')
_WIDTHS = dict.fromkeys((0x82,0x85,0x87,0x8d,0x8f,0x95,0x9b,0x9c,0x9e,0xa0,0xa2,0xa6,0xa8,0xa9), 1)
_WIDTHS.update(dict.fromkeys((0x86,0x9d,0xa3,0xa4,0xa5), 2))
_WIDTHS.update(dict.fromkeys((0x88,0x89,0x97), 3))
_WIDTHS.update(dict.fromkeys((0x83,0x8a,0x8c,0x8e,0x91,0x92,0x93,0x94,0x96,0x99,0x9a,0x9f), 0))
_WIDTHS[0x84] = 7
_BINARY_WIDTHS = _WIDTHS | {0x98:0, 0xaa:1, 0xab:1, 0xac:0, 0xb0:1}
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


def _track(data, start, end, waves, *, instruments=None, drums=b'', effects=False):
    at = start
    tick = fixed = wave = 0
    transpose = cutoff = endit = 0
    velocity = volume = 127
    pan = 64
    binary = instruments is not None
    widths = _BINARY_WIDTHS if binary else _WIDTHS
    explicit_velocity = binary and not effects
    ignore_fixed = ignore_transpose = False
    drum_bank = None
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
            if binary and strength & 128:
                strength &= 127
                velocity = strength
                explicit_velocity = False
            length = fixed if fixed and not ignore_fixed else variable()
            ignore_fixed = False
            if cmd != 0x60:
                voice, note_pan = wave, pan
                key = cmd if ignore_transpose else cmd + transpose
                if drum_bank is not None:
                    slot = (drum_bank+cmd)*6
                    if slot+6 > len(drums):
                        raise ValueError
                    voice, note_pan, key = drums[slot+1], drums[slot+4]>>1, drums[slot+5]
                if binary:
                    if not 0 <= voice < len(instruments):
                        raise ValueError
                    voice = instruments[voice]
                if cmd > 0x60 or voice not in waves:
                    raise ValueError
                ignore_transpose = False
                duration = min(length, cutoff) if cutoff else max(0, length-endit)
                notes.append(Note(tick, duration, key, voice, strength, note_pan, volume))
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
        width = 0 if effects and cmd==0x82 else widths.get(cmd)
        if width is None:
            raise ValueError
        args = [byte() for _ in range(width)]
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
        elif binary and cmd == 0x9e:
            drum_bank = args[0]
        elif binary and cmd == 0x9f:
            drum_bank = None
        elif binary and cmd == 0xac:
            fixed = 0
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


_BINARY_HEADER = struct.Struct('>10I')
# Fixed initial arithmetic bits of the binary song magic and track count.
_BINARY_PACKED = re.compile(rb'\xff\xff\xfb\x9d\x19\xff')


def binary_song(data, waves):
    if len(data) < 56:
        return None
    version, count, instruments, table, volume, bend, envelope, drum, voices, master = _BINARY_HEADER.unpack_from(data)
    if (version != 0x215 or not 1 <= count <= 32 or not 1 <= instruments <= 256 or table != 56
            or volume != table+count*4 or bend != volume+count*4 or voices != bend+count*4
            or not voices+instruments*2 <= min(envelope,drum) <= max(envelope,drum) <= master < len(data)):
        return None
    lookup = struct.unpack_from(f'>{instruments}H', data, voices)
    if not set(lookup) <= waves:
        return None
    tracks = struct.unpack_from(f'>{count}I', data, table)
    if tuple(sorted(set(tracks))) != tracks or not master < tracks[0] <= tracks[-1] < len(data):
        return None
    if any(offset and not max(envelope,drum) <= offset < master
           for offset, in struct.iter_unpack('>I', data[volume:voices])):
        return None
    events, tempos, loops = [], [], 0
    try:
        for start, end in zip((master,*tracks), (*tracks,len(data))):
            extent, notes, changes, repeats = _track(data,start,end,waves,instruments=lookup,
                                               drums=data[drum:master])
            events.extend(notes)
            tempos.extend(changes)
            loops += repeats
    except ValueError:
        return None
    return dict(notes=events, tempos=tempos, loops=loops, channels=count, extent=extent) if events else None


def binary_effects(data, waves):
    if len(data) < 24:
        return None
    count, second, third, reserved, drum, instruments = _HEADER.unpack_from(data)
    start = 24+count*8
    if (not (1 <= second <= count <= 2048 and 1 <= third <= 2048) or reserved or drum
            or not start < instruments < len(data) or len(data)-instruments != third*2):
        return None
    lookup = struct.unpack_from(f'>{third}H', data, instruments)
    if not set(lookup) <= waves:
        return None
    tracks = [offset for offset,_ in struct.iter_unpack('>2I', data[24:start])]
    if sorted(set(tracks)) != tracks or tracks[0] != start or tracks[-1] >= instruments:
        return None
    scores = []
    try:
        for at,end in zip(tracks, (*tracks[1:],instruments)):
            _,notes,tempos,loops = _track(data,at,end,waves,instruments=lookup,effects=True)
            if not notes:
                return None
            scores.append(dict(notes=notes,tempos=tempos,loops=loops,channels=1))
    except ValueError:
        return None
    return scores


def _effects_region(image, bank, waves, check):
    end = bank['offset']+bank['size']
    order = bank.get('control_byte_order','big')
    # Arithmetic renormalization can read one lookahead byte from a
    # following section. Confirm little-endian effects against both neighbors.
    for start in range((end+2)&~3, min(end+32,len(image)-8), 4):
        if order == 'big' and image[start-4:start] != b'\0\0\0\1':
            continue
        try:
            data, size = lzari.unpack(image[start:start+_MAX_BYTES],order=order,limit=_MAX_BYTES,check=check)
        except lzari.LzariError:
            continue
        if order == 'little' and not 0 <= bank['table_offset']-start-size <= 8:
            continue
        scores = binary_effects(data,waves)
        if scores is None:
            continue
        return dict(offset=start, size=size, kind='audio sequence', media='audio',
                    audio_kind='indexed sample directory', control=bank['offset'],
                    compressed_control=bank['compressed_control'], table_offset=bank['table_offset'],
                    control_byte_order=order, sequence_byte_order=order,
                    samples=[dict(label=f'Effect {i}',codec='Nintendo libmus') for i in range(1,len(scores)+1)],
                    layout='libmus-binary-effects', confidence='validated', label='libmus sequenced effects',
                    channels=1, notes=sum(len(score['notes']) for score in scores), loops=0,
                    reason='The adjacent LZARI effects directory resolves its tracks to the preceding verified wave bank.',
                    preview_settings=dict(format='auto', source='rom', offset=start))
    return None


def _wave_tail_songs(image, bank, waves, check):
    """Walk eight-byte-aligned songs immediately after a bank's wave table."""
    end = max(sample['offset']+sample['size'] for sample in bank['samples'])
    start = (end+7)&~7
    for _ in range(128):
        check()
        if image[start:start+4] != b'\0\0\x02\x15':
            break
        score = binary_song(image[start:start+_MAX_BYTES],waves)
        if score is None:
            break
        yield start,score['extent'],score
        start = (start+score['extent']+7)&~7



def _binary_regions(image, banks, check):
    packed_banks = sorted((bank for bank in banks if bank.get('compressed_control') and bank.get('control_codec') != 'rnc'),
                          key=lambda bank:bank['offset'])
    if not packed_banks:
        return []
    matches = []
    for index, match in enumerate(_BINARY_PACKED.finditer(image)):
        if index == 128:
            break
        start = match.start()-4
        if start < 4 or start%4 or image[start-4:start] != b'\0\0\0\1':
            continue
        check()
        try:
            data, size = lzari.unpack(image[start:start+_MAX_BYTES],limit=_MAX_BYTES,check=check)
        except lzari.LzariError:
            continue
        matches.append((start,size,data))
    assets = []
    song_number = 0
    for bank in packed_banks:
        end = bank['offset']
        waves = {sample['instrument'] for sample in bank['samples']}
        adjacent = []
        for start, size, data in reversed(matches):
            if start >= end:
                continue
            if not 0 <= end-start-size <= 32:
                break
            score = binary_song(data,waves)
            if score is None:
                break
            adjacent.append((start,size,score))
            end = start
        raw = list(_wave_tail_songs(image,bank,waves,check))
        songs = [(start,size,score,True) for start,size,score in reversed(adjacent)]
        songs.extend((start,size,score,False) for start,size,score in raw)
        for start,size,score,packed in songs:
            song_number += 1
            assets.append(dict(offset=start, size=size, kind='music sequence', media='audio',
                               audio_kind='indexed sample directory', control=bank['offset'],
                               compressed_control=bank['compressed_control'], table_offset=bank['table_offset'],
                               control_byte_order=bank.get('control_byte_order','big'), sequence_packed=packed,
                               samples=[dict(offset=start, size=size, codec='Nintendo libmus', label=f'Song {song_number}')],
                               layout='libmus-binary-song', confidence='validated', label=f'libmus binary song {song_number}',
                               channels=score['channels'], notes=len(score['notes']), loops=score['loops'],
                               reason=('Adjacent LZARI song streams resolve to the following control bank.' if packed else
                                       'Aligned song streams resolve to the preceding wave bank.'),
                               preview_settings=dict(format='auto', source='rom', offset=start)))
        if effects := _effects_region(image,bank,waves,check):
            assets.append(effects)
    return assets


def _rnc_regions(image, bank, check):
    waves = {sample['instrument'] for sample in bank['samples']}
    control = bank['offset']
    end = control+bank['size']
    table = bank['table_offset']
    found = []
    # Each following sequence starts at the next eight-byte alignment.
    for _ in range(128):
        check()
        start = (end+7)&~7
        if start >= table or any(image[end:start]):
            break
        try:
            data, size = rnc.unpack_at(image, start, max_output=_MAX_BYTES)
        except rnc.RncError:
            break
        if start+size > table or not (score := binary_song(data,waves)):
            break
        found.append((start,size,[score],False))
        end = start+size
    for match in ptr_audio.RNC_HEADER.finditer(image,max(0,control-_MAX_BYTES),control):
        check()
        start = match.start()
        if start%8 or start+18 > control:
            continue
        size = 18+int.from_bytes(image[start+8:start+12],'big')
        if (start+size+7)&~7 != control or any(image[start+size:control]):
            continue
        try:
            data, _ = rnc.unpack_at(image, start, max_output=_MAX_BYTES)
        except rnc.RncError:
            continue
        if scores := binary_effects(data,waves):
            found.append((start,size,scores,True))
    for start,size,scores,effects in found:
        kind = 'audio sequence' if effects else 'music sequence'
        layout = 'libmus-binary-effects' if effects else 'libmus-binary-song'
        label = 'libmus sequenced effects' if effects else 'libmus binary song'
        yield dict(offset=start,size=size,kind=kind,media='audio',audio_kind='indexed sample directory',
                   control=control,compressed_control=bank['compressed_control'],control_codec='rnc',
                   table_offset=table,sequence_codec='rnc',layout=layout,confidence='validated',label=label,
                   samples=[dict(label=f'Effect {index}' if effects else 'Song', codec='Nintendo libmus')
                            for index in range(1,len(scores)+1)],
                   channels=max(score['channels'] for score in scores),
                   notes=sum(len(score['notes']) for score in scores),loops=sum(score['loops'] for score in scores),
                   reason='The aligned RNC sequence resolves every instrument to the validated wave bank.',
                   preview_settings=dict(format='auto',source='rom',offset=start))


def _raw_control_sequence(image, bank):
    if bank.get('table_confidence') != 'adjacent wave and control pair':
        return None
    end = bank['offset']+bank['size']
    aligned = (end+7)&~7
    waves = {sample['instrument'] for sample in bank['samples']}
    for start in (aligned,aligned+8):
        if any(image[end:start]) or start+_HEADER.size > len(image):
            return None
        raw = image[start:start+_MAX_BYTES]
        if score := binary_song(raw,waves):
            scores = [score]
            size = score['extent']
            kind, layout, label = 'music sequence','libmus-binary-song','libmus binary song'
            break
        _, _, instruments, _, _, lookup = _HEADER.unpack_from(raw)
        size = lookup+2*instruments
        if _HEADER.size <= size <= len(raw) and (scores := binary_effects(raw[:size],waves)):
            kind, layout, label = 'audio sequence','libmus-binary-effects','libmus sequenced effects'
            break
    else:
        return None
    samples = [dict(label=f'Effect {i}' if kind == 'audio sequence' else 'Song',codec='Nintendo libmus')
               for i in range(1,len(scores)+1)]
    return dict(offset=start,size=size,kind=kind,media='audio',
                audio_kind='indexed sample directory',control=bank['offset'],table_offset=bank['table_offset'],
                sequence_packed=False,layout=layout,confidence='validated',label=label,samples=samples,
                channels=max(score['channels'] for score in scores),notes=sum(len(score['notes']) for score in scores),
                loops=sum(score['loops'] for score in scores),
                reason='The aligned sequence after the control graph resolves every instrument to its paired wave table.',
                preview_settings=dict(format='auto',source='rom',offset=start))


def _versioned_effects(image, bank):
    """Read an uncompressed effects directory after a versioned control graph."""
    end = bank['offset']+bank['size']
    if image[end:end+12] != bytes.fromhex('000000000000000200000004'):
        return None
    start = end+12
    if start+_HEADER.size > len(image):
        return None
    _, _, instruments, _, _, lookup = _HEADER.unpack_from(image, start)
    size = lookup+2*instruments
    if not _HEADER.size <= size <= _MAX_BYTES or start+size > len(image):
        return None
    waves = {sample['instrument'] for sample in bank['samples']}
    scores = binary_effects(image[start:start+size], waves)
    if not scores:
        return None
    return dict(offset=start, size=size, kind='audio sequence', media='audio',
                audio_kind='indexed sample directory', control=bank['offset'], table_offset=bank['table_offset'],
                sequence_packed=False, layout='libmus-binary-effects', confidence='validated',
                label='libmus sequenced effects',
                samples=[dict(label=f'Effect {i}', codec='Nintendo libmus') for i in range(1,len(scores)+1)],
                channels=1, notes=sum(len(score['notes']) for score in scores),
                loops=sum(score['loops'] for score in scores),
                reason='The versioned effects directory resolves every track to the unique inferred wave bank.',
                preview_settings=dict(format='auto', source='rom', offset=start))


def _split_raw_sequences(image, banks, check):
    """Read the split music/effects layout with 64-byte cartridge alignment."""
    if len(banks) != 2:
        return []
    music, effects = sorted(banks, key=lambda bank: bank['offset'])
    # The effects directory sits between the music control and the effects
    # wave table. The songs follow the effects control and use the music bank.
    effects_start = (music['offset'] + music['size'] + 63) & ~63
    next_wave = effects['table_offset']
    song_start = (effects['offset'] + effects['size'] + 63) & ~63
    if not (music['table_offset'] < music['offset'] < effects_start < next_wave < effects['offset'] < song_start
            and all(bank[field] % 64 == 0 for bank in banks for field in ('offset', 'table_offset'))
            and next_wave - effects_start <= _MAX_BYTES
            and not any(image[music['offset'] + music['size']:effects_start])
            and image[song_start:song_start + 4] == b'\0\0\x02\x15'):
        return []
    if effects_start + _HEADER.size > next_wave:
        return []
    _, _, instruments, _, _, lookup = _HEADER.unpack_from(image, effects_start)
    effects_end = effects_start + lookup + instruments * 2
    if not effects_start < effects_end <= next_wave or ((effects_end + 63) & ~63) != next_wave:
        return []
    effect_waves = {sample['instrument'] for sample in effects['samples']}
    scores = binary_effects(image[effects_start:effects_end], effect_waves)
    if not scores:
        return []
    music_waves = {sample['instrument'] for sample in music['samples']}
    songs = []
    distinct_banks = False
    for _ in range(128):
        check()
        if image[song_start:song_start + 4] != b'\0\0\x02\x15':
            break
        raw = image[song_start:song_start + _MAX_BYTES]
        score = binary_song(raw, music_waves)
        if not score:
            return []
        songs.append((song_start, score))
        distinct_banks |= binary_song(raw[:score['extent']], effect_waves) is None
        end = song_start + score['extent']
        song_start = (end + 63) & ~63
        if any(image[end:song_start]):
            break
    if not distinct_banks or len(songs) < 2:
        return []

    def asset(bank, offset, size, entries, *, is_effect):
        layout = 'libmus-binary-effects' if is_effect else 'libmus-binary-song'
        kind = 'audio sequence' if is_effect else 'music sequence'
        label = 'libmus sequenced effects' if is_effect else 'libmus binary song'
        samples = [dict(label=f'Effect {index}' if is_effect else 'Song', codec='Nintendo libmus')
                   for index in range(1, len(entries) + 1)]
        return dict(offset=offset, size=size, kind=kind, media='audio', audio_kind='indexed sample directory',
                    control=bank['offset'], table_offset=bank['table_offset'], sequence_packed=False,
                    layout=layout, confidence='validated', label=label, samples=samples,
                    channels=max(score['channels'] for score in entries),
                    notes=sum(len(score['notes']) for score in entries), loops=sum(score['loops'] for score in entries),
                    preview_settings=dict(format='auto', source='rom', offset=offset),
                    reason='The cartridge-aligned sequence and instrument table resolve to its split libmus bank.')

    result = [asset(effects, effects_start, effects_end - effects_start, scores, is_effect=True)]
    result.extend(asset(music, start, score['extent'], [score], is_effect=False) for start, score in songs)
    return result



def _archived_songs(image, banks, check):
    if not banks:
        return
    for offset, end in raw_deflate_lists.archive_spans(image, check):
        check()
        entries = raw_deflate_lists.members(image, offset, end - offset, b'\xaa\xa5')
        if len(entries) < 2 or any(member[:4] != b'\0\0\x02\x15' or len(member) > _MAX_BYTES for member in entries):
            continue
        matches = []
        for bank in banks:
            waves = {sample['instrument'] for sample in bank['samples']}
            scores = []
            for entry in entries:
                check()
                score = binary_song(entry, waves)
                if not score or not 0 <= len(entry) - score['extent'] <= 16:
                    break
                scores.append(score)
            else:
                matches.append((bank, scores))
        if len(matches) != 1:
            continue
        bank, scores = matches[0]
        samples = [dict(label=f'Song {i}', codec='Nintendo libmus', preview_available=True)
                   for i in range(1, len(scores) + 1)]
        yield dict(offset=offset, size=end - offset, kind='music sequence', media='audio',
                   audio_kind='indexed sample directory', control=bank['offset'], table_offset=bank['table_offset'],
                   sequence_codec='raw-deflate-directory', layout='libmus-binary-song',
                   confidence='validated', label='Compressed libmus song directory', samples=samples,
                   channels=max(score['channels'] for score in scores),
                   notes=sum(len(score['notes']) for score in scores), loops=sum(score['loops'] for score in scores),
                   reason='Every indexed song resolves to the same unique sample bank.',
                   preview_settings=dict(format='auto', source='rom', offset=offset))


def _contiguous_raw_songs(image, banks, check):
    """Find runs of aligned binary songs tied to one validated bank."""
    banks = [bank for bank in banks if not bank.get('compressed_control')
             and bank.get('table_offset') is not None]
    if not banks:
        return []
    assets = []
    cursor = 0
    for match in re.finditer(rb'\0\0\x02\x15', image):
        start = match.start()
        if start < cursor or start % 2:
            continue
        check()
        matches = []
        for bank in banks:
            waves = {sample['instrument'] for sample in bank['samples']}
            songs, at = [], start
            for _ in range(128):
                check()
                if image[at:at+4] != b'\0\0\x02\x15':
                    break
                score = binary_song(image[at:at+_MAX_BYTES], waves)
                if score is None:
                    break
                end = at+score['extent']
                if end > len(image) or binary_song(image[at:end], waves) is None:
                    break
                songs.append((at,score))
                next_two = (end+1)&~1
                next_sixteen = (end+15)&~15
                if start%16 == 0 and image[next_two:next_two+4] != b'\0\0\x02\x15':
                    at = next_sixteen
                else:
                    at = next_two
            if len(songs) >= 3:
                matches.append((bank,songs))
        if len(matches) != 1:
            continue
        bank, songs = matches[0]
        for index,(offset,score) in enumerate(songs,1):
            size = score['extent']
            assets.append(dict(offset=offset, size=size, kind='music sequence', media='audio',
                               audio_kind='indexed sample directory', control=bank['offset'],
                               table_offset=bank['table_offset'], sequence_packed=False,
                               layout='libmus-binary-song', confidence='validated',
                               label=f'libmus song {index}', channels=score['channels'],
                               notes=len(score['notes']), loops=score['loops'],
                               samples=[dict(offset=offset, size=size, codec='Nintendo libmus',
                                             label=f'Song {index}', preview_available=True)],
                               reason='A contiguous run of complete songs resolves to one validated wave bank.',
                               preview_settings=dict(format='auto', source='rom', offset=offset)))
        cursor = songs[-1][0]+songs[-1][1]['extent']
    return assets


def regions(image, banks, *, check=lambda: None):
    resolved = [bank for bank in banks if bank['offset'] == bank['bank_offset'] and bank['samples']]
    assets = _binary_regions(image,resolved,check)
    assets.extend(_archived_songs(image, resolved, check))
    for bank in resolved:
        if bank.get('control_codec') == 'rnc':
            assets.extend(_rnc_regions(image,bank,check))
    raw = [bank for bank in resolved if not bank.get('compressed_control')]
    assets.extend(_split_raw_sequences(image, raw, check))
    assets.extend(sequence for bank in raw if (sequence := _raw_control_sequence(image,bank)) is not None)
    if len(raw) == 1 and (effects := _versioned_effects(image, raw[0])):
        assets.append(effects)
    existing = {asset['offset'] for asset in assets}
    assets.extend(asset for asset in _contiguous_raw_songs(image, raw, check) if asset['offset'] not in existing)
    if len(raw) != 1:
        return assets
    bank = raw[0]
    waves = {sample['instrument'] for sample in bank['samples']}
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
    index = formats.integer(selection['sample'], 'Sequence', 0, len(asset['samples'])-1)
    base = asset['table_offset']
    books = None
    try:
        if span := asset.get('compressed_control'):
            start, size = span
            books = ptr_audio.decoded_control(image, asset)
            bank = {**ptr_audio.bank(books, 0), 'offset':start, 'size':size}
        else:
            bank = ptr_audio.bank(image, asset['control'])
    except (audio.BankError, lzari.LzariError, rnc.RncError) as exc:
        raise formats.AssetError('The libmus wave bank changed. Rescan ROM Explorer.') from exc
    if (image[base:base+len(ptr_audio.WAVES)] != ptr_audio.WAVES
            or not ptr_audio.fits(image, bank, base, [ptr_audio.MAX_FRAME_CHECKS], lambda: None)):
        raise formats.AssetError('The libmus wave table failed sample validation. Rescan ROM Explorer.')
    waves = {sample['instrument']:sample for sample in bank['samples']}
    start, size = asset['offset'], asset['size']
    score = None
    if 0 <= start < start+size <= len(image):
        raw = image[start:start+size]
        if asset['layout'] == 'libmus-raw-song':
            score = song(raw,waves)
        else:
            try:
                if asset.get('sequence_codec') == 'raw-deflate-directory':
                    entries = raw_deflate_lists.members(image, start, size, b'\xaa\xa5')
                    raw = entries[index] if index < len(entries) else b''
                elif asset.get('sequence_codec') == 'rnc':
                    raw, extent = rnc.unpack_at(raw, 0, max_output=_MAX_BYTES)
                    if extent != size:
                        raise rnc.RncError('changed packed sequence size')
                elif asset.get('sequence_packed',True):
                    raw, _ = lzari.unpack(raw,order=asset.get('sequence_byte_order','big'),limit=_MAX_BYTES)
                if asset['layout'] == 'libmus-binary-effects':
                    scores = binary_effects(raw,set(waves))
                    if scores and index < len(scores):
                        score = scores[index]
                else:
                    score = binary_song(raw,set(waves))
            except (lzari.LzariError, rnc.RncError):
                pass
    if score is None:
        raise formats.AssetError('The libmus channel data changed. Rescan ROM Explorer.')

    tempos = [Event(tick, 0xff, tuple((60_000_000//bpm).to_bytes(4, 'big')))
              for tick, bpm in score['tempos']]
    voices = []
    for note in score['notes']:
        sample = waves[note.wave]
        pitch = note.key + _signed(sample['base_note_byte']-48) + sample['detune']/100
        gain = (note.volume*note.velocity/127**2)**2 if pitch <= 12 else 0
        if asset['layout'] == 'libmus-binary-effects' and not sample.get('loop', {}).get('count'):
            # An effect can hold a note until its wave ends. Stop nonlooping
            # waves at that point instead of extending the WAV with silence.
            ticks = math.ceil(96*sample['samples']/sample['rate']/2**(pitch/12))
            note = replace(note,duration=min(note.duration,ticks))
        voices.append((note, dict(sample=sample, pitch=pitch, pan=note.pan, gain=gain)))
    pcm, stats = compact_midi_render.render(image, base, 48, tempos, voices, label='libmus', book_image=books)
    payload, details = formats.pcm(pcm, dict(format='pcm-s16le', channels=2,
                                           rate=compact_midi_render.RATE, length=len(pcm)))
    details.update(stats, format='Nintendo libmus', sample=index,
                   note='Single-pass sample-backed preview. Envelopes, ties and modulation can differ.')
    return dict(media='audio', mime='audio/wav', details=details,
                data_url='data:audio/wav;base64,'+base64.b64encode(payload).decode(),
                settings={**asset['preview_settings'], 'sample':index})
