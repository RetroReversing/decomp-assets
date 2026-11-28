"""libmus PtrTablesV2 control graphs and uniquely fitting marked WaveTables.

The layout follows ptr_bank_t (libmus_data.h) and original loader relocations.
A bank contains no sample rate; preview rates are user choices, not imported facts.
"""
from __future__ import annotations

import itertools
import re
import struct
from bisect import bisect_left

from .. import rnc
from ..formats import MAX_BYTES, AssetError, integer
from . import audio, lzari

MAGIC=b'N64 PtrTablesV2\0'
WAVES=b'N64 WaveTables \0'
# The first encoded bits of the fixed PtrTablesV2 header, before any
# bank-specific fields. Full decompression and graph validation follow.
_LZARI_PREFIX = bytes.fromhex('c0437af8c1cfa2dfb61d888b')
_MAX_PACKED = 2*1024*1024
RNC_HEADER = re.compile(rb'RNC[\x01\x02]')
_RNC_LOOKBACK = 512*1024
MAX_BANKS=128
MAX_SAMPLES=2048
MAX_CONTROL=1024*1024
MAX_FRAME_CHECKS=4*1024*1024
DEFAULT_RATE=22050


def bank(image,offset, *, check=lambda:None):
    """Validate unrelocated wave records, tuning arrays, loops and order-2 books."""
    end=offset+48;limit=min(len(image),offset+MAX_CONTROL)
    def take(at,size,alignment=4):
        nonlocal end
        if at<48 or at%alignment or size<0 or offset+at+size>limit:raise audio.BankError('Invalid pointer-bank extent.')
        end=max(end,offset+at+size);return image[offset+at:offset+at+size]
    if end>len(image) or image[offset:offset+16]!=MAGIC:raise audio.BankError('Not a pointer bank.')
    if int.from_bytes(image[offset+16:offset+20],'big'):raise audio.BankError('The pointer bank is already relocated.')
    count,notes,tuning,table=struct.unpack_from('>4I',image,offset+32)
    if not 1<=count<=MAX_SAMPLES:raise audio.BankError('Invalid pointer-bank sample count.')
    note_data=take(notes,count,1);tune_data=take(tuning,count*4);pointers=take(table,count*4)
    if any(tune_data[i:i+3]!=b'\0\0\0' for i in range(1,len(tune_data),4)):raise audio.BankError('Invalid unrelocated tuning arrays.')
    samples=[];skipped_loops=0
    for index in range(count):
        check();at=struct.unpack_from('>I',pointers,index*4)[0]
        if not at:continue
        record=take(at,20);base,length=struct.unpack_from('>II',record);codec,flags=record[8:10];loop,book=struct.unpack_from('>II',record,12)
        if codec not in (0,1) or flags or base<16 or base%16 or not 0<length<=MAX_BYTES:raise audio.BankError('Invalid wave record.')
        item=dict(relative_offset=base,size=length,codec='N64 VADPCM' if codec==0 else 'PCM16 big endian',rate=DEFAULT_RATE,instrument=index,base_note_byte=note_data[index],detune=tune_data[index*4] if tune_data[index*4]<128 else tune_data[index*4]-256)
        if codec==0:
            if length<9 or length%9 not in (0,1) or length%9==1 and length%2:raise audio.BankError('Incomplete ADPCM frames.')
            order,predictors=struct.unpack('>II',take(book,8))
            if order!=2 or not 1<=predictors<=8:raise audio.BankError('Unsupported ADPCM book.')
            take(book,8+predictors*32)
            item.update(book_offset=offset+book+8,predictors=predictors,samples=length//9*16,encoded_size=length//9*9)
        else:
            if length%2:raise audio.BankError('Incomplete PCM samples.')
            item['samples']=length//2
        if loop:
            start,finish,repeats=struct.unpack_from('>III',take(loop,44 if codec==0 else 12))
            if not start<=finish<=item['samples']:
                # A large bank can contain one broken loop without invalidating
                # its other independent wave records. Never expose that sample.
                if not (codec == 0 and start <= item['samples'] < finish <= 2*item['samples']):
                    raise audio.BankError('Loop exceeds sample extent.')
                skipped_loops+=1
                continue
            item['loop']=dict(start=start,end=finish,count=repeats)
        samples.append(item)
    if not samples or skipped_loops and (skipped_loops != 1 or len(samples)<16):
        raise audio.BankError('No sufficiently validated waves.')
    name=bytes(image[offset+20:offset+32]).split(b'\0')[0].decode('ascii',errors='replace')
    return dict(offset=offset,size=end-offset,samples=samples,name=name,skipped_invalid_loops=skipped_loops)


def fits(image,info,base,budget,check):
    for sample in info['samples']:
        start=base+sample['relative_offset'];end=start+sample['size']
        if end>len(image) or start<info['offset']+info['size'] and info['offset']<end:return False
        if sample['codec']=='N64 VADPCM':
            if any(image[start+sample['encoded_size']:end]):return False
            for at in range(start,start+sample['encoded_size'],9):
                if budget[0]<=0:return False
                budget[0]-=1
                if at%4096<9:check()
                if image[at]&15>=sample['predictors']:return False
    return True


def _compressed(image, *, check):
    for match in itertools.islice(re.finditer(re.escape(_LZARI_PREFIX), image), MAX_BANKS):
        check()
        start = match.start()-4
        if start < 0 or start%4:
            continue
        candidates = []
        packed = image[start:start+_MAX_PACKED]
        for order in ('big','little'):
            try:
                decoded, extent = lzari.unpack(packed, order=order, limit=MAX_CONTROL, check=check)
                info = bank(decoded, 0, check=check)
            except (lzari.LzariError, audio.BankError):
                continue
            if len(decoded) == info['size']:
                candidates.append({**info, 'offset':start, 'size':extent,
                                   'compressed_control':(start,extent), 'control_byte_order':order})
        if len(candidates) == 1:
            yield candidates[0]


def _rnc_controls(image, tables, check):
    # RNC sound bundles put their marked waves after their control and sequences.
    seen = set()
    for table in tables:
        for match in RNC_HEADER.finditer(image, max(0, table-_RNC_LOOKBACK), table):
            check()
            start = match.start()
            if start%8 or start in seen:
                continue
            seen.add(start)
            try:
                decoded, extent = rnc.unpack_at(image, start, max_output=MAX_CONTROL, max_packed=_MAX_PACKED)
                if start+extent > table or not decoded.startswith(MAGIC):
                    continue
                info = bank(decoded, 0, check=check)
            except (rnc.RncError, audio.BankError):
                continue
            if len(decoded) == info['size']:
                yield {**info, 'offset':start, 'size':extent, 'control_codec':'rnc',
                       'compressed_control':(start,extent)}


def decoded_control(image, asset):
    start, size = asset['compressed_control']
    if asset.get('control_codec') == 'rnc':
        decoded, extent = rnc.unpack_at(image, start, max_output=MAX_CONTROL, max_packed=_MAX_PACKED)
    else:
        decoded, extent = lzari.unpack(image[start:start+size], order=asset.get('control_byte_order','big'),
                                       limit=MAX_CONTROL)
    if extent != size:
        raise audio.BankError('Changed compressed control length.')
    return decoded


def _controls(image, tables, *, check):
    for hit in itertools.islice(re.finditer(re.escape(MAGIC),image),MAX_BANKS):
        check()
        try:
            yield bank(image,hit.start(),check=check)
        except audio.BankError:
            pass
    yield from _compressed(image,check=check)
    yield from _rnc_controls(image,tables,check)


def regions(image, *, check=lambda:None, progress=lambda _:None):
    """Keep ambiguous wave-table placement unresolved instead of choosing the nearest."""
    tables=[m.start() for m in itertools.islice(re.finditer(re.escape(WAVES),image),MAX_BANKS)]
    results=[];budget=[MAX_FRAME_CHECKS]
    for index,info in enumerate(_controls(image,tables,check=check)):
        check();progress(dict(phase='Recognizing libmus audio banks',done=index))
        preceding = bisect_left(tables,info['offset'])-1
        pairs = []
        if preceding >= 0 and not info.get('compressed_control'):
            base = tables[preceding]
            finish = max(base+s['relative_offset']+s['size'] for s in info['samples'])
            # Some resource streams store one wave table, its eight-byte
            # terminator/alignment, then the matching raw control graph.
            if (((finish+7)&~7)+8 == info['offset'] and not any(image[finish:info['offset']])
                    and fits(image,info,base,[MAX_FRAME_CHECKS],check)):
                pairs.append(base)
        if not info.get('compressed_control'):
            # Some resource files store the validated control first, followed
            # immediately by its aligned marked waves. A game's relocated
            # sample pointer independently confirmed this layout at runtime.
            finish = info['offset']+info['size']
            base = (finish+15)&~15
            if (base in tables and not any(image[finish:base])
                    and fits(image,info,base,[MAX_FRAME_CHECKS],check)):
                pairs.append(base)
        paired = pairs[0] if len(pairs) == 1 else None
        if len(pairs) > 1:
            fitting = pairs
        else:
            fitting = [paired] if paired is not None else [base for base in tables if fits(image,info,base,budget,check)]
        resolved=len(fitting)==1 and (paired is not None or budget[0]>0)
        base=fitting[0] if resolved else None
        samples=[{**s,'offset':base+s['relative_offset']} for s in info['samples']] if resolved else []
        reason='PtrTablesV2 control graph, tuning arrays, sample extents, loops and predictor books checked. '+('Exactly one marked WaveTables candidate fits every sample and ADPCM frame selector; table placement remains a static inference.' if resolved else 'Wave-table placement is ambiguous or unresolved; sample bytes are not classified.')+' The bank stores no rate: 22050 Hz is an editable preview default. Pitch, mixing, sequences and loop playback are not recreated.'
        if paired is not None:
            reason = 'A marked WaveTables block and this validated control graph are adjacent with only alignment padding. '
            reason += 'The bank stores no rate. 22050 Hz is an editable preview default.'
        if info['skipped_invalid_loops']:
            reason += ' One sample with an out-of-range loop was omitted.'
        common=dict(media='audio',audio_kind='libmus sample bank',bank_offset=info['offset'],rate_basis='Editable preview rate; not stored in the bank',table_confidence=('adjacent wave and control pair' if paired is not None else 'unique marked table (static inference)') if resolved else 'unresolved',table_candidates=fitting,table_offset=base,reason=reason,skipped_invalid_loops=info['skipped_invalid_loops'])
        if 'compressed_control' in info:
            common.update(compressed_control=info['compressed_control'])
            common.update((key, info[key]) for key in ('control_codec', 'control_byte_order') if key in info)
        results.append(dict(offset=info['offset'],size=info['size'],kind='audio',label='libmus '+info['name'] if info['name'] else 'libmus sample bank',confidence='validated',samples=samples,sample_count=len(info['samples']),preview_settings=dict(format='auto',source='rom',offset=info['offset']),**common))
        if resolved:
            seen=set()
            for sample in samples:
                key=sample['offset'],sample['size']
                if key in seen:continue
                seen.add(key)
                results.append(dict(offset=sample['offset'],size=sample['size'],kind='audio',label='libmus sample '+str(sample['instrument']+1),confidence='tentative',samples=[sample],preview_settings=dict(format='auto',source='rom',offset=sample['offset']),**common))
    return results


def preview(image,asset,selection):
    if asset.get('audio_kind')=='libmus sequence':raise AssetError('This is a sequence candidate, not a waveform. Sequence playback is not implemented; choose a sample from Audio browser.')
    if not asset.get('samples'):raise AssetError('The pointer bank has no uniquely fitting marked wave table. Inspect its table candidates in ROM Explorer before preparing audio.')
    rate=integer(selection.get('rate',DEFAULT_RATE),'Preview sample rate',1000,192000)
    selected={**asset,'samples':[{**s,'rate':rate} for s in asset.get('samples',[])]}
    books = None
    if asset.get('compressed_control'):
        try:
            books = decoded_control(image, asset)
        except (audio.BankError, lzari.LzariError, rnc.RncError) as exc:
            raise AssetError('The compressed audio controls changed. Rescan ROM Explorer.') from exc
    result=audio.preview(image,selected,selection,book_image=books)
    result['settings']['rate']=rate;result['details']['rate_basis']=asset['rate_basis']
    return result


def sequence_layout(data):
    """Recognize the older indexed channel header without executing track commands."""
    if len(data)<24:return None
    count,notes,volume,bend,envelope,drums=struct.unpack_from('>6I',data)
    if not 1<=count<=32 or notes!=24 or volume!=notes+count*4 or bend!=volume+count*4 or envelope!=bend+count*4 or not envelope<=drums<len(data):return None
    offsets=struct.unpack_from('>'+str(count*3)+'I',data,notes)
    if not any(offsets[:count]) or any(at and not envelope<=at<len(data) for at in offsets):return None
    return dict(sequence_channels=count,active_channels=sum(bool(at) for at in offsets[:count]))


def sequences(image, *, check=lambda:None, progress=lambda _:None):
    """Describe CRC-checked archived channel tables as unrendered sequence candidates."""
    from .. import archives as asset_archives
    results=[];expanded=0
    for member in asset_archives.zip_members(image,check=check):
        check()
        if not member['name'].lower().endswith('.bin'):continue
        if expanded+member['expanded']>16*1024*1024:break
        expanded+=member['expanded']
        try:data=asset_archives.member_bytes(image,member)
        except AssetError:continue
        info=sequence_layout(data)
        if info:
            results.append(dict(offset=member['offset'],size=member['size'],kind='music sequence',confidence='tentative',media='audio',audio_kind='libmus sequence',label=member['name'],samples=[],archive=member,**info,
                                reason='ZIP member CRC passed; indexed channel, volume and pitch-stream pointers fit. Track commands and musical interpretation are not verified. This is a sequence candidate, not a recorded waveform; sequence playback is not implemented.',preview_settings=dict(format='auto',source='rom',offset=member['offset'])))
    return results
