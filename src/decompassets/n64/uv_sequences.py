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



def _adjacent_directory(image, tail):
    # Cartridge banks can align the next directory to a DMA boundary.
    return next((offset for offset in ((tail + 3) & ~3, (tail + 15) & ~15)
                 if image[offset:offset + 2] == b'S1' and not any(image[tail:offset])), None)

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


# A detached directory starts at relative offset zero. Its second entry
# starts at the first sequence's declared length.
_DETACHED_INDEX = re.compile(rb'\0{4}(\0(?:[\x01-\x03]..|\0(?:[\x01-\xff].|\0[\x45-\xff])))\1', re.S)


def _detached_rows(image, index, start, check):
    cursor = 0
    remaining_events = 256 * 1024
    rows, scores = [], []
    for i in range(128):
        check()
        if index+8*(i+1) > start:
            break
        offset, length = _ENTRY.unpack_from(image, index+i*8)
        if offset != cursor or not length:
            break
        if length > 256*1024 or cursor+length > formats.MAX_BYTES or start+offset+length > len(image):
            return [], []
        at = start+offset
        score = compact_midi.sequence(image[at:at+length])
        if score is None:
            return [], []
        division, events = score
        remaining_events -= len(events)
        if remaining_events < 0:
            return [], []
        notes = sum(e.status & 0xf0 == 0x90 and e.duration > 0 and e.data[1] > 0 for e in events)
        rows.append(dict(offset=at, size=length, division=division, notes=notes))
        scores.append(events)
        cursor += length
    return rows, scores


def _bank_covers(scores, programs):
    for events in scores:
        total = found = 0
        for _, voice in note_voices(events, programs):
            total += 1
            found += voice is not None
        if not total or found*10 < total*9:
            return False
    return True


def _detached_directories(image, sound_banks, check):
    # Use validated sample extents only. A sequence can follow a different
    # bank from the one that supplies the sequence player's instruments.
    controls = {asset['offset']: asset for asset in sound_banks
                if len(asset.get('samples', ())) > 1 and asset.get('table_confidence') == 'validated'
                and image[asset['offset']:asset['offset']+2] == b'B1'}
    anchors = set()
    for asset in controls.values():
        check()
        start = (_sample_end(asset['samples'], asset['table_offset'])+15)&~15
        if image[start:start+4] == b'\0\0\0D':
            anchors.add(start)
    programs = {}
    for start in sorted(anchors):
        candidates = []
        for match in islice(_DETACHED_INDEX.finditer(image, 0, start), 2048):
            check()
            index = match.start()
            if index%4:
                continue
            rows, scores = _detached_rows(image, index, start, check)
            if len(rows) >= 3:
                candidates.append((index, rows, scores))
                if len(candidates) > 1:
                    break
        if len(candidates) != 1:
            continue
        index, rows, scores = candidates[0]
        if not programs:
            for address in controls:
                try:
                    programs[address] = audio.bank(image, address, check=check)['programs']
                except audio.BankError:
                    continue
        matches = [control for control, graph in programs.items() if _bank_covers(scores, graph)]
        control = matches[0] if len(matches) == 1 else None
        end = rows[-1]['offset']+rows[-1]['size']
        asset = _asset(start, end, rows, 'Compact MIDI music bank',
                       ('A detached offset-and-length table bounds every compact MIDI sequence. One validated bank matches the instruments used.'
                        if control is not None else 'A detached offset-and-length table bounds every compact MIDI sequence.'),
                       control)
        asset['detached_index'] = index
        if control is not None:
            asset['table_offset'] = controls[control]['table_offset']
        yield asset


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
        offset = _adjacent_directory(image, tail)
        if offset is None or offset in found:
            continue
        rows = _entries(image, offset, len(image), check, exact=False)
        if rows:
            found.add(offset)
            end = (rows[-1]['offset']+rows[-1]['size']+3)&~3
            asset = _asset(offset, end, rows, 'Compact MIDI music directory',
                           'A complete S1 directory follows the validated adjacent sample table.',
                           control)
            result.append({**asset, 'table_offset':base})
    result.extend(_detached_directories(image, sound_banks, check))
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
    if 'detached_index' in asset:
        base = asset['table_offset']
        rows, _ = _detached_rows(image, asset['detached_index'], asset['offset'], lambda: None)
        if rows != asset['sequences']:
            raise formats.AssetError('The detached music directory changed. Rescan ROM Explorer.')
        bank['corroborated'] = True
    elif 'table_offset' in asset:
        base = asset['table_offset']
        tail = _sample_end(bank['samples'], base)
        if base != (control+bank['size']+15)&~15 or _adjacent_directory(image, tail) != asset['offset']:
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
    score = compact_midi.sequence(image[start:start+size]) if asset['offset'] <= start < start+size <= end <= len(image) else None
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
