"""Standard MIDI records following their bounded named B1 sound bank."""
import base64
import re
import struct

from .. import formats
from . import audio, compact_midi_render, standard_midi, uv_sequences

LAYOUT = 'named-record-midi'
_NAME = re.compile(rb'[A-Za-z0-9_-]{1,12}\.mid')


def _rows(image, start, programs, check):
    rows = []
    cursor = start
    while cursor+46 <= len(image) and len(rows) < 4096:
        check()
        size, reserved = struct.unpack_from('>II', image, cursor)
        name = image[cursor+8:cursor+24].split(b'\0', 1)[0]
        if reserved or not _NAME.fullmatch(name) or size < 46 or cursor+size > len(image):
            break
        data = image[cursor+24:cursor+size]
        if data[:4] != b'MThd':
            break
        end = 22+int.from_bytes(data[18:22], 'big')
        if not 0 <= len(data)-end < 8 or not (score := standard_midi.sequence(data[:end])):
            break
        _, events = score
        if not any(voice is not None for _, voice in uv_sequences.note_voices(events, programs)):
            break
        rows.append(dict(label=name.decode('ascii'), offset=cursor+24, size=end,
                         codec='Standard MIDI', preview_available=True))
        cursor += size
    return rows


def regions(image, *, sound_banks=(), check=lambda: None, progress=lambda _: None):
    found = []
    for item in sound_banks:
        control = item['offset']
        if item.get('table_layout') != 'named-records' or image[control:control+2] != b'B1':
            continue
        try:
            bank = audio.bank(image, control, check=check)
        except audio.BankError:
            continue
        record = audio._named_audio_records(image, [(control, False)], check).get(control)
        if not record or record[1] != item.get('table_offset'):
            continue
        start = record[0]
        rows = _rows(image, start, bank['programs'], check)
        if len(rows) < 2:
            continue
        end = rows[-1]['offset']+rows[-1]['size']
        found.append(dict(offset=start, size=end-start, kind='music sequence', media='audio',
                          audio_kind='indexed sample directory', layout=LAYOUT,
                          label='Named MIDI tracks', confidence='validated', control=control,
                          table_offset=record[1], samples=rows,
                          preview_settings=dict(source='rom', format='auto', offset=start),
                          reason='Adjacent named MIDI records follow a validated sound bank and resolve notes through its samples.'))
    return found


def preview(image, asset, selection):
    control, base = asset['control'], asset['table_offset']
    try:
        bank = audio.bank(image, control)
    except audio.BankError as exc:
        raise formats.AssetError('The song bank changed. Rescan ROM Explorer.') from exc
    record = audio._named_audio_records(image, [(control, False)], lambda: None).get(control)
    if (not record or record[0] != asset['offset'] or record[1] != base
            or not audio._fits(image, bank, base, [audio.MAX_HEADER_CHECKS], lambda: None)):
        raise formats.AssetError('The song bank changed. Rescan ROM Explorer.')
    rows = _rows(image, record[0], bank['programs'], lambda: None)
    index = formats.integer(selection.get('sample', 0), 'Song', 0, len(rows)-1)
    row = rows[index]
    score = standard_midi.sequence(image[row['offset']:row['offset']+row['size']])
    if score is None:
        raise formats.AssetError('The song directory changed. Rescan ROM Explorer.')
    division, events = score
    pcm, stats = compact_midi_render.render(image, base, division, events,
                                            uv_sequences.note_voices(events, bank['programs']), label='Standard MIDI')
    payload, details = formats.pcm(pcm, dict(format='pcm-s16le', channels=2, rate=compact_midi_render.RATE,
                                             length=len(pcm)))
    details.update(stats, format='Standard MIDI', sample=index,
                   note='Single-pass sample-backed preview. Envelopes and bends during held notes can differ.')
    return dict(media='audio', mime='audio/wav', details=details,
                data_url='data:audio/wav;base64,'+base64.b64encode(payload).decode(),
                settings={**asset['preview_settings'], 'sample':index})
