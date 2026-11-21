"""DIET-packed B1 controls followed by waves and Standard MIDI tracks."""

from .. import formats
from ..formats import AssetError
from . import audio, compact_midi_render, diet, standard_midi, uv_sequences

BANK = 'diet-b1-bank'
SONG = 'diet-midi'


def _bank(image, end, data, check):
    try:
        bank = audio.bank(data,0,check=check)
    except audio.BankError:
        return None
    base = (end+15)&~15
    if len(data)-bank['size'] > 15 or any(data[bank['size']:]) or any(image[end:base]):
        return None
    tail = max(base+sample['relative_offset']+sample['size'] for sample in bank['samples'])
    next_block = (tail+15)&~15
    if (image[next_block:next_block+len(diet.MAGIC)] != diet.MAGIC or any(image[tail:next_block])
            or not audio._fits(image,bank,base,[audio.MAX_HEADER_CHECKS],check)):
        return None
    return bank,base,next_block


def regions(image, *, check=lambda: None, progress=lambda _: None):
    assets = []
    adjacent = None
    for at,end,data in diet.members(image,check=check):
        progress(dict(phase='Reading packed B1 audio',done=at,total=len(image)))
        if data.startswith(b'B1'):
            adjacent = None
            if not (parsed := _bank(image,end,data,check)):
                continue
            bank,base,next_block = parsed
            samples = [{**sample,'offset':base+sample['relative_offset']} for sample in bank['samples']]
            assets.append(dict(offset=at,size=end-at,kind='audio',media='audio',audio_kind='B1 sample bank',
                               layout=BANK,label='Compressed B1 sample bank',confidence='validated',
                               control=at,table_offset=base,samples=samples,
                               reason='The checked DIET control graph and adjacent aligned wave frames agree.',
                               preview_settings=dict(format='auto',source='rom',offset=at)))
            adjacent = at,base,next_block,bank['programs']
            continue
        if adjacent is None or at != adjacent[2] or not (score := standard_midi.sequence(data)):
            adjacent = None
            continue
        control,base,_,programs = adjacent
        _,events = score
        notes = sum(voice is not None for _,voice in uv_sequences.note_voices(events,programs))
        if not notes:
            adjacent = None
            continue
        adjacent = control,base,(end+15)&~15,programs
        assets.append(dict(offset=at,size=end-at,kind='music sequence',media='audio',audio_kind='indexed sample directory',
                           layout=SONG,label='Standard MIDI song',confidence='validated',control=control,
                           table_offset=base,samples=[dict(label='Song',codec='Standard MIDI')],notes=notes,
                           reason='The checked MIDI track follows the wave table and resolves notes through its B1 bank.',
                           preview_settings=dict(format='auto',source='rom',offset=at)))
    return assets


def preview(image, asset, selection):
    at = asset['control']
    controls,end = diet.unpack(image,at)
    parsed = _bank(image,end,controls,lambda: None)
    if parsed is None or parsed[1] != asset['table_offset']:
        raise AssetError('The compressed B1 audio changed. Rescan ROM Explorer.')
    bank,base,_ = parsed
    if asset['layout'] == BANK:
        samples = [{**sample,'offset':base+sample['relative_offset']} for sample in bank['samples']]
        return audio.preview(image,{**asset,'samples':samples},selection,book_image=controls)
    if 'sample' not in selection:
        return dict(media='metadata',title=asset['label'],fields={'Notes with a bank voice':asset['notes']},
                    settings=asset['preview_settings'])
    formats.integer(selection['sample'],'Song',0,0)
    data,end = diet.unpack(image,asset['offset'])
    score = standard_midi.sequence(data)
    if score is None or end != asset['offset']+asset['size']:
        raise AssetError('The Standard MIDI song changed. Rescan ROM Explorer.')
    division,events = score
    voices = uv_sequences.note_voices(events,bank['programs'])
    pcm,stats = compact_midi_render.render(image,base,division,events,voices,label='Standard MIDI',book_image=controls)
    payload,details = formats.pcm(pcm,dict(format='pcm-s16le',channels=2,rate=compact_midi_render.RATE,offset=0))
    import base64
    return dict(media='audio',mime='audio/wav',data_url='data:audio/wav;base64,'+base64.b64encode(payload).decode(),
                details={**details,**stats,'format':'Standard MIDI','note':asset['reason']},
                settings={**asset['preview_settings'],'sample':0})
