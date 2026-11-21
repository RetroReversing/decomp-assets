"""Two relocated libaudio banks sharing one table before an indexed cue tree.

Format reference: https://github.com/mgrz18/turok2-decomp/blob/main/docs/assets/AUDIO.md
"""

import base64
import re
import struct

from .. import formats
from . import audio, compact_midi, compact_midi_render, textures, uv_sequences

_DIRECTORY = re.compile(rb'\x00\x00\x00\x02.{4}\x00\x00\x00\x00.{8}B1', re.DOTALL)
_HEADER = struct.Struct('>5I')
_MIX_RATE = 22050


def _cue_tree(image, start):
    if start+16 > len(image) or image[start:start+4] != b'\0\0\0\2':
        return None
    size = struct.unpack_from('>I', image, start+12)[0]
    if not 16 < size <= min(8*1024*1024, len(image)-start):
        return None
    children = textures._blocks(image, start, start+size, empty=True)
    if not children:
        return None
    effects, cues = [textures._blocks(image, *span, empty=True) for span in children]
    if effects is not None and len(effects) == 6 and cues is not None and len(cues) == 2:
        return cues
    return None


def _extent(bank):
    return max(sample['relative_offset']+sample['size'] for sample in bank['samples'])


def _parse(image, offset, check, budget):
    _, first, _, second, split = _HEADER.unpack_from(image, offset)
    size = _HEADER.size
    control = first-size
    middle = second-control
    if control <= 0 or control % 4 or not size+8 <= middle <= audio.MAX_CONTROL or middle % 4:
        return None
    if image[offset+middle:offset+middle+2] != b'B1':
        return None
    try:
        music = audio.bank(image, offset+size, relocation_base=first, control_end=offset+middle, check=check)
        effects = audio.bank(image, offset+middle, relocation_base=second, check=check)
    except audio.BankError:
        return None
    if (min(s['relative_offset'] for s in music['samples']) != 0
            or min(s['relative_offset'] for s in effects['samples']) != split
            or ((_extent(music)+7)&~7) != split):
        return None
    end = effects['offset']+effects['size']
    matches = []
    for base in range((end+3)&~3, min(end+64,len(image)), 4):
        check()
        if any(image[end:base]):
            break
        tail = base+_extent(effects)
        tree = (tail+3)&~3
        if any(image[tail:tree]) or not _cue_tree(image, tree):
            continue
        if all(audio._fits(image, bank, base, budget, check) for bank in (music, effects)):
            matches.append((base, tree))
    if len(matches) != 1:
        return None
    base, tree = matches[0]
    music.update(relocation=first, control_end=offset+middle)
    return music, effects, base, tree


SEQUENCE_LAYOUT = 'paired-b1-compact-midi'


def _sequences(image, tree, music, base, check):
    cue_spans = _cue_tree(image, tree)
    keys, records = cue_spans
    if keys[1]-keys[0] < 12:
        return None
    width, count = struct.unpack_from('>II', image, keys[0])
    if width != 4 or not 1 <= count <= 256 or keys[1]-keys[0] != ((8+4*count+7)&~7):
        return None
    cue_ids = struct.unpack_from(f'>{count}I', image, keys[0]+8)
    if list(cue_ids) != sorted(cue_ids):
        return None
    spans = textures._blocks(image, *records, empty=True)
    if spans is None or len(spans) != 2*count:
        return None
    samples = []
    for cue, header, body in zip(cue_ids, spans[::2], spans[1::2]):
        check()
        lo, hi = body
        if header[1]-header[0] != 8:
            return None
        decoded = compact_midi.sequence(image[lo:hi])
        if decoded is None:
            # The directory can also hold streamed codecs. Leave those slots
            # to their own recognizers rather than classifying them as songs.
            continue
        _, events = decoded
        audible = any(event.status&0xf0 == 0x90 and event.duration and event.data[1] for event in events)
        samples.append(dict(offset=lo, size=hi-lo, codec='Nintendo compact MIDI',
                            label=f'Cue {cue}', preview_available=audible))
    if not samples:
        return None
    return dict(offset=records[0], size=records[1]-records[0], kind='music sequence',
                media='audio', audio_kind='indexed sample directory', layout=SEQUENCE_LAYOUT,
                label='Music sequences', confidence='validated', samples=samples,
                reason='Indexed cue records contain valid compact MIDI and share relocated music samples.',
                control=music['offset'], relocation=music['relocation'], control_end=music['control_end'],
                table_offset=base, preview_settings=dict(format='auto', source='rom', offset=records[0]))


def preview(image, asset, selection):
    index = formats.integer(selection.get('sample', 0), 'Sample', 0, len(asset['samples'])-1)
    row = asset['samples'][index]
    try:
        music = audio.bank(image, asset['control'], relocation_base=asset['relocation'],
                           control_end=asset['control_end'])
    except audio.BankError as exc:
        raise formats.AssetError('The music bank changed. Rescan ROM Explorer.') from exc
    score = compact_midi.sequence(image[row['offset']:row['offset']+row['size']])
    if score is None:
        raise formats.AssetError('The music sequence changed. Rescan ROM Explorer.')
    division, events = score
    # The engine plays these samples at mixer rate for a unity pitch ratio.
    # The nominal sample rate in the serialized ALBank is unused.
    for sample in music['samples']:
        sample['rate'] = _MIX_RATE
    pcm, stats = compact_midi_render.render(image, asset['table_offset'], division, events,
                                            uv_sequences.note_voices(events, music['programs']))
    wav, details = formats.pcm(pcm, dict(format='pcm-s16le', channels=2, rate=compact_midi_render.RATE,
                                         length=len(pcm)))
    details.update(stats, format='Nintendo compact MIDI', sample=index,
                   note='Single-pass sample-backed preview. Runtime effects and envelopes can differ.')
    return dict(media='audio', mime='audio/wav', details=details,
                data_url='data:audio/wav;base64,'+base64.b64encode(wav).decode('ascii'),
                settings=dict(asset['preview_settings'], sample=index))


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    budget = [audio.MAX_HEADER_CHECKS]
    for index, match in enumerate(_DIRECTORY.finditer(image)):
        if index >= audio.MAX_CANDIDATES:
            break
        check()
        progress(dict(phase='Recognizing paired N64 audio banks', done=index))
        parsed = _parse(image, match.start(), check, budget)
        if parsed is None:
            continue
        music, effects, base, tree = parsed
        for label, bank in (('Music samples', music), ('Sound effects', effects)):
            samples = [{**sample, 'offset': base+sample['relative_offset'], 'rate': _MIX_RATE}
                       for sample in bank['samples']]
            offset = bank['offset']
            result.append(dict(offset=offset, size=bank['size'], label=label, kind='audio', media='audio',
                               audio_kind='sample bank', samples=samples, confidence='validated',
                               table_confidence='validated', table_offset=base,
                               reason='Paired relocated B1 graphs, shared sample extents, ADPCM frame selectors '
                                      'and the following indexed cue tree agree. Preview plays the sample at unity pitch.',
                               preview_settings=dict(format='auto', source='rom', offset=offset)))
        if catalog := _sequences(image, tree, music, base, check):
            result.append(catalog)
    return result
