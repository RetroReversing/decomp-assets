"""Audio resources paired by the Iguana cartridge directory."""

import base64
import re
import struct

from .. import formats
from . import audio, compact_midi, compact_midi_render, dean_audio, dean_codec, iguana_archive, uv_sequences

_BANK_REASON = 'The named control and wave files, relocated pointer graph and sample frames agree.'
_DEAN_REASON = 'The named commentary file has a complete indexed directory of DEAN stream extents.'
_SEQUENCE_REASON = 'The named sound file contains bounded compact MIDI sequences paired with the first music bank.'


def _bank(image, offset, start, end, wave, wave_end, check):
    if offset+8>end:
        return None
    relative = offset-start
    pointer = int.from_bytes(image[offset+4:offset+8], 'big')-relative
    first = max(4096, (pointer-(end-offset)+4096)&~4095)
    last = pointer&~4095
    if last-first>audio.MAX_CONTROL:
        return None
    banks = []
    for base in range(first,last+1,4096):
        try:
            info = audio.bank(image, offset, relocation_base=base+relative, control_end=end, check=check)
        except audio.BankError:
            continue
        info['corroborated'] = True
        if (all(sample['relative_offset']+sample['size']<=wave_end-wave for sample in info['samples'])
                and audio._fits(image, info, wave, [audio.MAX_HEADER_CHECKS], check)):
            banks.append((base+relative,info))
    return banks[0] if len(banks)==1 else None


def _banks(image, control, waves, *, check):
    start, end = control
    wave, wave_end = waves
    if not 8 <= end-start <= audio.MAX_CONTROL:
        return []
    output = []
    for hit in re.compile(b'B1').finditer(image, start, end):
        check()
        offset = hit.start()
        if (offset-start)%4 or not (verified := _bank(image,offset,start,end,wave,wave_end,check)):
            continue
        relocation, info = verified
        samples = [dict(s,offset=wave+s['relative_offset']) for s in info['samples']]
        output.append(dict(offset=offset,size=info['size'],kind='audio',media='audio',audio_kind='sample bank',
                           label='Iguana music wave bank',confidence='validated',reason=_BANK_REASON,
                           table_offset=wave, control_end=end, relocation=relocation, samples=samples,
                           preview_settings=dict(format='auto',source='rom',offset=offset)))
    return output


def _dean_rows(image, start, end, codebooks, check):
    if end-start < 12:
        return []
    count, = struct.unpack_from('>I', image, start)
    cursor = start+4+4*count
    if not 2<=count<=2048 or cursor>=end:
        return []
    result = []
    for index in range(count):
        check()
        offset = start+int.from_bytes(image[start+4+index*4:start+8+index*4], 'big')
        if offset!=cursor or offset+12>end:
            return []
        rate, frames, length = dean_audio.ROW.unpack_from(image, offset)
        payload_end = offset+12+length
        cursor = (payload_end+3)&~3
        if (not 4000<=rate<=48000 or not 2<=frames<=65536 or not 4<=length<=dean_audio.MAX_ENTRY
                or cursor>end or any(image[payload_end:cursor])):
            return []
        sample = dict(offset=offset+12,size=length,codec='Acclaim DEAN',rate=rate,label=f'Clip {index+1}',
                      samples=(frames-1)*dean_codec.BLOCK_SAMPLES,preview_available=codebooks is not None)
        result.append(dict(offset=offset,size=cursor-offset,kind='audio',media='audio',
                           audio_kind='dean stream',layout='iguana-dean',label=f'Iguana commentary clip {index+1}',
                           confidence='validated',reason=_DEAN_REASON,samples=[sample],dean_codebooks=codebooks,
                           preview_settings=dict(format='auto',source='rom',offset=offset)))
    return result if cursor==end else []


def _sequences(image, start, end, bank, check):
    if end-start<16:
        return None
    groups, first, second, extent = struct.unpack_from('>4I',image,start)
    if groups!=2 or first!=16 or not first<second<=extent-4 or extent!=end-start:
        return None
    at = start+second
    count, = struct.unpack_from('>I',image,at)
    if not 1<=count<=128 or at+4+4*count>=end:
        return None
    offsets = struct.unpack_from(f'>{count}I',image,at+4)
    table_end = at+4+count*4
    if (tuple(sorted(set(offsets)))!=offsets or offsets[0]<table_end-at
            or offsets[-1]>=end-at or offsets[0]-table_end+at not in (0,4,8)):
        return None
    padding = image[table_end:at+offsets[0]]
    if padding and (int.from_bytes(padding[:4],'big')!=end-at or any(padding[4:])):
        return None
    samples = []
    for index,(lo,hi) in enumerate(zip(offsets,(*offsets[1:],end-at))):
        check()
        if lo%4 or not 0<hi-lo<=256*1024:
            return None
        decoded = compact_midi.sequence(image[at+lo:at+hi])
        if decoded is None:
            return None
        _, events = decoded
        has_notes = any(event.status&0xf0==0x90 and event.duration and event.data[1] for event in events)
        samples.append(dict(offset=at+lo,size=hi-lo,codec='Nintendo compact MIDI',label=f'Sequence {index+1}',
                            preview_available=has_notes))
    return dict(offset=at,size=end-at,kind='music sequence',media='audio',audio_kind='indexed sample directory',
                layout='iguana-compact-midi',label='Iguana music sequences',confidence='validated',
                reason=_SEQUENCE_REASON,samples=samples,control=bank['offset'],control_end=bank['control_end'],
                table_offset=bank['table_offset'],relocation=bank['relocation'],
                preview_settings=dict(format='auto',source='rom',offset=at))


def regions(image, *, check=lambda:None, progress=lambda _:None):
    assets = []
    for directory in iguana_archive.directories(image,check=check):
        control = directory.get(b'data/sound/music.ctl')
        waves = directory.get(b'data/sound/music.tbl')
        if control and waves:
            banks = _banks(image,control,waves,check=check)
            assets.extend(banks)
            sequence = directory.get(b'data/sound/sfx.fsd')
            if banks and banks[0]['offset']==control[0] and sequence:
                if catalog := _sequences(image,*sequence,banks[0],check):
                    assets.append(catalog)
        if commentary := directory.get(b'data/sound/pbpsfx.bin'):
            assets.extend(_dean_rows(image,*commentary,dean_codec.table_offset(image),check))
    return assets


def preview(image, asset, selection):
    index = formats.integer(selection.get('sample',0),'Sample',0,len(asset['samples'])-1)
    settings = dict(asset['preview_settings'],sample=index)
    selected = asset['samples'][index]
    if asset['layout']=='iguana-dean':
        rate, frames, length = dean_audio.ROW.unpack_from(image, asset['offset'])
        if (selected['rate'],selected['size'],selected['samples']) != (rate,length,(frames-1)*dean_codec.BLOCK_SAMPLES):
            raise formats.AssetError('The DEAN clip header changed. Rescan ROM Explorer.')
        start = selected['offset']
        if asset['dean_codebooks'] is None:
            return dict(media='metadata',title='Acclaim DEAN audio',fields={'Playback':'Codebooks unavailable'},
                        settings=settings)
        return dean_audio.render_clip(image,asset['dean_codebooks'],image[start:start+length],rate,frames,settings)
    try:
        bank = audio.bank(image,asset['control'],relocation_base=asset['relocation'],control_end=asset['control_end'])
    except audio.BankError as exc:
        raise formats.AssetError('The Iguana music bank changed. Rescan ROM Explorer.') from exc
    start = selected['offset']
    score = compact_midi.sequence(image[start:start+selected['size']])
    if score is None:
        raise formats.AssetError('The Iguana music sequence changed. Rescan ROM Explorer.')
    division, events = score
    pcm, stats = compact_midi_render.render(image,asset['table_offset'],division,events,
                                            uv_sequences.note_voices(events,bank['programs']))
    wav, details = formats.pcm(pcm,dict(format='pcm-s16le',channels=2,rate=compact_midi_render.RATE,length=len(pcm)))
    details.update(stats, format='Nintendo compact MIDI', sample=index,
                   note='Single-pass sample-backed preview. Envelopes and bends during held notes can differ.')
    return dict(media='audio',mime='audio/wav',details=details,settings=settings,
                data_url='data:audio/wav;base64,'+base64.b64encode(wav).decode('ascii'))
