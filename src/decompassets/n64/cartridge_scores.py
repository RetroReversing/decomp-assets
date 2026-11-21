"""Compressed cartridge scores with separate per-song track counts and B1 instrument banks."""

import base64
import re
import struct
from dataclasses import replace
from itertools import islice

from .. import formats
from . import audio, compact_midi_render, paired_resources
from .compact_midi import Event

LAYOUT = 'n64-cartridge-scores'
_WIDTHS = (1, 2, 1, 2, 3, 1, 2, 2, 1, 1, 1, 0, 0, 1, 2, 1,
           1, 3, 1, 3, 3, 3, 1, 0, 3, 0, 3, 0, 0, 0, 0, 1,
           1, 0, 1, 2, 0, 0, 0, 0, 3, 2, 1, 2, 3, 3, 3, 0)
# The sequencer callback runs every 5,000 microseconds.
_CLOCK = 100
_MAX_SCORE = 64 * 1024
_MAX_COMMANDS = 16000
_FRAME_TICKS = 200
_MAX_TICKS = _FRAME_TICKS * formats.MAX_SECONDS


def _signed(value):
    return value if value < 128 else value - 256


def _offsets(data):
    start = int.from_bytes(data[:2], 'big')
    if start % 2 or not 2 <= start <= 40 or start >= len(data):
        return ()
    starts = struct.unpack_from(f'>{start // 2}H', data)
    if starts == tuple(sorted(set(starts))) and starts[-1] < len(data):
        return starts
    return ()


def _track(data, start, end, bank, programs, patches, budget):
    elapsed = 0.0
    step = 128
    length = gate = 1
    program = transpose = fine = patch_pitch = 0
    volume, pan = 127, 64
    repeats = {}
    loops = {}
    main_loop = None
    section = None
    section_end = None
    section_pass = 0
    notes = []
    position = start
    for _ in range(_MAX_COMMANDS):
        budget[0] -= 1
        if budget[0] < 0 or not start <= position < end:
            break
        opcode = data[position]
        position += 1
        if opcode < 0xd0:
            key = opcode % 0x68
            if key == 0x67:
                if position >= end:
                    break
                key = data[position]
                position += 1
            if opcode < 0x68:
                if position >= end:
                    break
                length = data[position]
                position += 1
            if position >= end:
                break
            if data[position] < 0x80:
                gate = data[position]
                position += 1
            if position >= end:
                break
            velocity = data[position] & 0x7f
            position += 1
            duration = (length or 256) * 256 / step
            voice = programs.get((bank, program))
            if velocity and key < 128 and voice and elapsed < _MAX_TICKS:
                definition = voice[0]
                sample = definition['sample']
                pitch = key + patch_pitch + transpose + fine / 64 - definition['key_base']
                gain = (volume * velocity / 127**2)**2
                event = Event(round(elapsed), 0x90, (key, velocity), max(1, round(duration * (gate or 128) / 128)))
                notes.append((event, dict(sample=sample, pitch=max(-96, min(96, pitch)), pan=pan, gain=gain, bank=bank)))
            elapsed += duration
            continue

        width = _WIDTHS[opcode - 0xd0]
        if position + width > end:
            break
        first = data[position] if width else 0
        arguments = position
        position += width
        if opcode == 0xff:
            return notes
        if opcode == 0xd0:
            step = max(first, 1)
        elif opcode in (0xd2, 0xd3, 0xd4):
            if opcode >= 0xd3:
                volume = min(first, 127)
            program = data[arguments + int(opcode != 0xd2)]
            if bank >= len(patches) or program >= len(patches[bank]):
                return None
            patch = patches[bank][program]
            patch_pitch = _signed(patch[0]) + _signed(patch[1]) / 64
            pan = min(127, data[arguments + 2] if opcode == 0xd4 else patch[6])
        elif opcode == 0xd5:
            volume = min(first, 127)
        elif opcode == 0xdd:
            pan = min(first, 127)
        elif opcode == 0xdf:
            transpose = _signed(first)
        elif opcode == 0xe0:
            fine = _signed(first)
        elif opcode in (0xe7, 0xe9):
            loops[opcode + 1] = position
            repeats[opcode + 1] = 0
        elif opcode in (0xe8, 0xea):
            if opcode not in loops:
                return None
            repeats[opcode] += 1
            if not first:
                return notes
            if repeats[opcode] < first:
                transpose += _signed(data[arguments + 1]) / 256
                fine += _signed(data[arguments + 2]) * 2
                position = loops[opcode]
        elif opcode == 0xeb:
            main_loop = position
        elif opcode == 0xec:
            return notes if main_loop is not None else None
        elif opcode == 0xed:
            section, section_end, section_pass = position, None, 0
        elif opcode == 0xee and section is not None:
            if section_pass == 1:
                section_end, position = position, section
            elif section_pass > 1:
                position, section = section_end, None
            section_pass += 1
        elif opcode == 0xf0:
            bank = first
        elif opcode in (0xf2, 0xf3):
            duration = (first or 256) * 256 / step
            if opcode == 0xf3 and notes:
                event, voice = notes[-1]
                held = round(elapsed + duration * (data[arguments + 1] or 128) / 128) - event.tick
                notes[-1] = replace(event, duration=max(event.duration, held)), voice
            elapsed += duration
    return None


def _score(data, bank, programs, patches, budget):
    offsets = _offsets(data)
    if not offsets:
        return None
    voices = []
    for start, end in zip(offsets, (*offsets[1:], len(data))):
        notes = _track(data, start, end, bank, programs, patches, budget)
        if notes is None:
            return None
        voices.extend(notes)
    return voices


def _entries(image, start, anchor):
    starts = []
    position = start
    expected = anchor
    while position + 4 <= len(image) and len(starts) < 128:
        offset, = struct.unpack_from('>I', image, position)
        if offset != expected:
            break
        packed = int.from_bytes(image[offset:offset + 4], 'big')
        if not 4 < packed <= _MAX_SCORE or offset + packed > len(image):
            break
        starts.append(offset)
        expected = offset + ((packed + 15) & ~15)
        position += 4
    if len(starts) < 4 or position + 4 * len(starts) > len(image):
        return ()
    ends = struct.unpack_from(f'>{len(starts)}I', image, position)
    if ends == (*starts[1:], expected):
        return tuple(zip(starts, ends))
    return ()


def _patches(image, start, counts):
    first_size, second_size = (7 * count for count in counts[:2])
    stride = (first_size + 3) & ~3
    matches = []
    for at in range(start, min(len(image) - stride - second_size - 8, start + 4096), 4):
        first, second = struct.unpack_from('>2I', image, at)
        if not 0x80000000 <= first < second < 0x81000000 or second - first != stride:
            continue
        rows = [tuple(struct.iter_unpack('7B', image[at + 8:at + 8 + first_size])),
                tuple(struct.iter_unpack('7B', image[at + 8 + stride:at + 8 + stride + second_size]))]
        default = at + 8 + stride + ((second_size + 3) & ~3)
        if default + 7 > len(image):
            continue
        rows.append((tuple(image[default:default + 7]),) * counts[2])
        if all(-48 <= _signed(p[0]) <= 48 and p[2] <= 127 and p[5] <= 127 and p[6] <= 127
               for bank in rows for p in bank):
            matches.append((at, rows))
    return matches[0] if len(matches) == 1 else (None, [])


def _programs(image, banks):
    maps = {}
    counts = []
    for index, (offset, _) in enumerate(banks):
        bank = audio.bank(image, offset)
        by_program = {program: voices for (part, program), voices in bank['programs'].items()
                      if part == 0 and isinstance(program, int)}
        if not by_program:
            return {}, ()
        counts.append(max(by_program) + 1)
        maps.update(((index, program), voices) for program, voices in by_program.items())
    return maps, tuple(counts)


def regions(image, sound_banks, *, check=lambda: None, progress=lambda _: None):
    banks = sorted((asset['offset'], asset) for asset in sound_banks
                   if asset.get('table_confidence') == 'validated' and len(asset.get('samples', ())) > 1
                   and asset.get('table_layout') == 'parallel')
    if len(banks) != 3:
        return []
    last = banks[-1][1]
    wave_end = max(last['table_offset'] + item['relative_offset'] + item['size'] for item in last['samples'])
    anchor = (wave_end + 15) & ~15
    marker = struct.pack('>I', anchor)
    matches = re.compile(re.escape(marker)).finditer(image, 0, min(len(image), 0x100000))
    for match in islice(matches, 64):
        index = match.start()
        if index % 4 or not (entries := _entries(image, index, anchor)):
            continue
        check()
        data = []
        for offset, _ in entries:
            check()
            size = int.from_bytes(image[offset:offset + 4], 'big')
            member = paired_resources.unpack(image, offset, size)
            if not member or len(member) > _MAX_SCORE:
                break
            data.append(member)
        if len(data) != len(entries):
            continue
        counts = [len(_offsets(member)) for member in data]
        if not all(counts):
            continue
        directory_end = index + len(entries) * 8
        signature = b''.join(re.escape(bytes([count])) + rb'[\0\x01]' for count in counts)
        metadata = list(re.compile(signature).finditer(image, directory_end, banks[0][0]))
        if len(metadata) != 1:
            continue
        source = [(offset, asset['table_offset']) for offset, asset in banks]
        programs, counts = _programs(image, source)
        patch_offset, patches = _patches(image, directory_end, counts)
        if patch_offset is None:
            continue
        rows = []
        groups = metadata[0][0][1::2]
        budget = [600_000]
        for number, ((offset, end), member, group) in enumerate(zip(entries, data, groups), 1):
            check()
            notes = _score(member, group, programs, patches, budget)
            if notes is None:
                break
            rows.append(dict(offset=offset, size=end - offset, channel_group=group, label=f'Sequence {number}',
                             codec='Cartridge score', preview_available=bool(notes), notes=len(notes)))
        else:
            return [dict(offset=anchor, size=entries[-1][1] - anchor, samples=rows, layout=LAYOUT,
                         kind='music sequence', media='audio', audio_kind='indexed sample directory',
                         label='Cartridge music sequences', confidence='validated', banks=source,
                         patch_offset=patch_offset,
                         preview_settings=dict(format='auto', source='rom', offset=anchor),
                         reason='The song extents and track counts agree with the cartridge directory and B1 banks.')]
    return []


def preview(image, asset, selection):
    index = formats.integer(selection.get('sample', 0), 'Sequence', 0, len(asset['samples']) - 1)
    row = asset['samples'][index]
    offset = row['offset']
    size = int.from_bytes(image[offset:offset + 4], 'big')
    data = paired_resources.unpack(image, offset, size) if 4 < size <= row['size'] else None
    source = asset['banks']
    try:
        programs, counts = _programs(image, source)
    except audio.BankError as exc:
        raise formats.AssetError('The music instrument bank changed. Rescan ROM Explorer.') from exc
    patch_offset, patches = _patches(image, asset['patch_offset'], counts)
    if not data or len(data) > _MAX_SCORE or patch_offset != asset['patch_offset']:
        raise formats.AssetError('The cartridge score changed. Rescan ROM Explorer.')
    voices = _score(data, row['channel_group'], programs, patches, [100_000])
    if not voices:
        raise formats.AssetError('The cartridge score has no playable notes.')
    tempo = [Event(0, 0xff, tuple((500_000).to_bytes(4, 'big')))]
    for _, voice in voices:
        voice['table_offset'] = source[voice['bank']][1]
    pcm, stats = compact_midi_render.render(image, source[0][1], _CLOCK, tempo, voices, label='Cartridge score')
    wav, details = formats.pcm(pcm, dict(format='pcm-s16le', channels=2, rate=compact_midi_render.RATE,
                                         length=len(pcm)))
    details.update(stats, format='Cartridge score', sample=index,
                   note='Single-pass sample playback with cartridge instruments. Live modulation and effects can differ.')
    return dict(media='audio', mime='audio/wav', details=details,
                data_url='data:audio/wav;base64,' + base64.b64encode(wav).decode('ascii'),
                settings=dict(asset['preview_settings'], sample=index))

