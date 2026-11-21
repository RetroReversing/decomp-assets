"""Source-assisted libultra B1 banks: bounded pointer graphs and explicit table evidence.

Control pointers are B1-relative or relocated by a checked wrapper. Sample offsets
are relative to a separate table.
ADPCM headers alone cannot locate that table. Named loader arguments corroborate it;
a unique adjacent structural candidate stays explicitly tentative without that evidence.
"""
from __future__ import annotations

import base64
import io
import itertools
import re
import struct
import wave

from ..formats import MAX_BYTES, MAX_SECONDS, AssetError, integer

MAX_CONTROL = 1024*1024
MAX_CANDIDATES = 128
MAX_INSTRUMENTS = 512  # Some effects banks index hundreds of sparse instrument slots.
MAX_SOUNDS = 4096
MAX_SAMPLES = 2048
MAX_TABLE_PROBES = 32
MAX_HEADER_CHECKS = 4*1024*1024
RELOCATED_BASE = 0x800000
B1_WRAPPER = struct.pack('>III', 1, RELOCATED_BASE+12, 0)


class BankError(ValueError):
    pass


class KeyMapError(BankError):
    """A bank has sample controls but no usable MIDI note mapping."""


def bank(image, offset, *, relocated=False, relocation_base=None, control_end=None, sample_only=False, check=lambda: None):
    """Check relocation flags, pointer graphs, predictor books and record extents."""
    if relocated and (offset < len(B1_WRAPPER) or image[offset-len(B1_WRAPPER):offset] != B1_WRAPPER):
        raise BankError('Missing relocated B1 wrapper.')
    end = offset+8
    if relocated:
        relocation_base = RELOCATED_BASE+len(B1_WRAPPER)
    expected_flag = int(relocation_base is not None)

    def resolve(value):
        return value-relocation_base if value and relocation_base is not None else value
    samples = {}; sounds = 0; visited = {}; programs = {}
    limit = min(len(image),offset+MAX_CONTROL,control_end if control_end is not None else len(image))

    def take(at, size, alignment=4):
        nonlocal end
        if at<4 or at%alignment or size<0 or offset+at+size>limit:raise BankError('Invalid bank pointer or extent.')
        end=max(end,offset+at+size)
        return image[offset+at:offset+at+size]

    def pointer(at):return resolve(int.from_bytes(take(at,4),'big'))

    unmapped = set()

    def instrument(at, rate, bank_index, instrument_index):
        nonlocal sounds
        if not at:return
        key=(at,rate)
        if key in visited:
            programs[bank_index,instrument_index] = visited[key]
            return
        voices = []
        visited[key] = programs[bank_index,instrument_index] = voices
        head=take(at,16);count=int.from_bytes(head[14:16],'big')
        if head[0]>127 or head[1]>127 or head[3]!=expected_flag or not 1<=count<=MAX_SOUNDS:raise BankError('Invalid instrument.')
        take(at,16+count*4)
        for index in range(count):
            check();sounds+=1
            if sounds>MAX_SOUNDS:raise BankError('Bank sound limit reached.')
            sound=pointer(at+16+index*4)
            if not sound:continue
            data=take(sound,16);envelope,keymap,wavetable=struct.unpack_from('>III',data)
            envelope,keymap,wavetable=map(resolve,(envelope,keymap,wavetable))
            if data[12]>127 or data[13]>127 or data[14]!=expected_flag:raise BankError('Invalid sound flags or gain.')
            env=take(envelope,16);keys=take(keymap,6,2)
            if any(value < -1 for value in struct.unpack_from('>iii',env)) or env[12]>127 or env[13]>127:raise BankError('Invalid envelope.')
            playable = keys[0] <= keys[1] and keys[2] <= keys[3] and max(keys[:5]) <= 127
            if not playable:
                if not sample_only:
                    raise KeyMapError('Invalid key map.')
                unmapped.add(keymap)
            sample_key = wavetable, rate
            if playable and not sample_only:
                voices.append(dict(sample_key=sample_key, velocity_range=tuple(keys[:2]), key_range=tuple(keys[2:4]),
                               key_base=keys[4], detune=keys[5] if keys[5] < 128 else keys[5]-256,
                               volume=data[13]*head[0]/127**2, pan=max(0, min(127, data[12]+head[1]-64))))
            if sample_key in samples:continue
            data=take(wavetable,20);base,length=struct.unpack_from('>II',data);codec,flags=data[8:10]
            loop,book=map(resolve,struct.unpack_from('>II',data,12))
            if codec not in (0,1) or flags!=expected_flag or not 0<length<=MAX_BYTES:raise BankError('Invalid wavetable.')
            sample=dict(relative_offset=base,size=length,rate=rate,codec='N64 VADPCM' if codec==0 else 'PCM16 big endian',
                        bank=bank_index,instrument=instrument_index,sound=index,key_base=keys[4])
            if codec==0:
                # Some bank builders retain an even-byte pad after odd frame counts.
                if length%9 not in (0,1) or length<9 or length%9==1 and length%2:raise BankError('ADPCM needs complete nine-byte frames, with at most an even-byte pad.')
                order,predictors=struct.unpack('>II',take(book,8))
                if order!=2 or not 1<=predictors<=8:raise BankError('Unsupported ADPCM book.')
                take(book,8+order*predictors*16)
                sample.update(book_offset=offset+book+8,predictors=predictors,samples=length//9*16,encoded_size=length//9*9)
            else:
                if length%2:raise BankError('PCM needs complete samples.')
                sample['samples']=length//2
            if loop:
                start,finish,count=struct.unpack_from('>III',take(loop,44 if codec==0 else 12))
                if not start<=finish<=sample['samples']:raise BankError('Loop exceeds sample extent.')
                sample['loop']=dict(start=start,end=finish,count=count)
            samples[sample_key]=sample
            if len(samples)>MAX_SAMPLES:raise BankError('Bank sample limit reached.')

    if offset+8>len(image) or image[offset:offset+2]!=b'B1':raise BankError('Not a B1 bank.')
    count=int.from_bytes(image[offset+2:offset+4],'big')
    if not 1<=count<=128:raise BankError('Invalid bank count.')
    take(4,count*4)
    for index in range(count):
        at=pointer(4+index*4);header=take(at,12)
        instruments,flags,pad,rate,percussion=struct.unpack('>HBBII',header)
        if flags!=expected_flag or pad or not 0<=instruments<=MAX_INSTRUMENTS or not 1000<=rate<=192000:raise BankError('Invalid bank header.')
        take(at,12+instruments*4)
        instrument(resolve(percussion),rate,index,'percussion')
        for number in range(instruments):instrument(pointer(at+12+number*4),rate,index,number)
    if not samples:raise BankError('Bank has no supported samples.')
    if sample_only and len(unmapped) < 2:
        raise KeyMapError('A single invalid key map does not establish a sample-only bank.')
    for voices in visited.values():
        for voice in voices:
            voice['sample'] = samples[voice.pop('sample_key')]
    return dict(offset=offset,size=end-offset,samples=list(samples.values()),sound_count=sounds,programs=programs)


def loader_tables(image, context, *, check=lambda: None):
    """Read explicit constant table arguments; never execute or patch the game's code.

    Finding them needs a reader of MIPS code, which this library doesn't have: the caller passes one as
    `context['read_code']` (decompdecomp's `arch.mips_assets.read`). Without one, no loader evidence is used.
    """
    read=context.get('read_code')
    if read is None:return {}
    functions=context.get('functions',[])
    targets={f['vram'] for f in functions if f['name'].lstrip('_')=='alBnkfNew'}
    targets.update(s['address'] for s in context.get('symbols',[]) if s['name'].lstrip('_')=='alBnkfNew')
    if not targets:return {}
    needles=[struct.pack('>I',3<<26 | (target>>2)&0x3ffffff) for target in targets]
    result={}
    for f in functions:
        check();offset=f.get('rom_offset')
        if offset is None or not 0<=offset<offset+f['size']<=len(image):continue
        code=image[offset:offset+min(f['size'],128*1024)]
        if not any(needle in code for needle in needles):continue
        for event in read(f['vram'],code,gp=context.get('gp',0),check=check)['events']:
            if event['kind']!='call' or event.get('target') not in targets:continue
            value=event['args'][1]
            if not value or value['kind']!='constant':continue
            base=value['value']
            if not 0<=base<len(image):continue
            result.setdefault(base,[]).append(dict(function=f['name'],instruction=event['instruction'],role='sample-table argument',
                                                   reason='Named alBnkfNew call supplies a constant sample-table argument; runtime execution is not established.'))
    return result


def _guards_b1(words):
    bases = {4, *(word >> 11 & 31 for word in words[:9] if word & 0xffff07ff == 0x00800021)}
    for i, signature in enumerate(words[:-2]):
        base = signature >> 21 & 31
        magic = words[i+1]
        if base not in bases or signature & 0xfc00ffff != 0x84000000 or magic & 0xffe0ffff != 0x24004231:
            continue
        if any(branch >> 26 == 5 and branch >> 21 & 31 == signature >> 16 & 31
               and branch >> 16 & 31 == magic >> 16 & 31 for branch in words[i+2:i+4]):
            return any(word & 0xffe0ffff == (0x84000002 | base << 21) for word in words[i+2:])
    return False


def _forwarded_control(events, pi_transfers, relocators):
    """Check a wrapper's control ROM argument, length and wave address reach their proper uses."""
    calls = [event for event in events if event['kind'] == 'call']
    for index, copy in enumerate(calls):
        if copy['target'] not in pi_transfers or len(copy['args']) < 6:
            continue
        source, buffer, size = copy['args'][3:6]
        if not (source and source['kind']=='argument' and source['value']==0 and not source['offset']
                and size and size['kind']=='argument' and size['value']==1 and not size['offset'] and buffer):
            continue
        # The wrapper may wait for the DMA completion message before relocating.
        for link in calls[index+1:index+4]:
            if link['block'] != copy['block'] or link['target'] not in relocators or len(link['args']) < 2:
                continue
            control, wave = link['args'][:2]
            if not (control and control['kind']=='memory' and not control.get('offset', 0) and wave and wave['kind']=='argument'
                    and wave['value']==3 and not wave['offset']):
                continue
            load = next((event for event in events if event['kind']=='load' and event['width']==4
                         and event['instruction']==control['value']), None)
            place = load and load['place']
            if not place or place['kind']!='constant' or not copy['instruction'] < load['instruction'] < link['instruction']:
                continue
            stores = [event for event in events if event['kind'] == 'store'
                      and event['block'] == copy['block'] and event['instruction'] < load['instruction']
                      and event['place'] and event['place']['kind'] == 'constant'
                      and event['place']['value'] == place['value']]
            written = max(stores, key=lambda event: event['instruction']) if stores else None
            if (written and written['instruction'] < copy['instruction'] and written['width'] == 4
                    and written['value'] and all(written['value'].get(key) == buffer.get(key)
                                                 for key in ('kind', 'value', 'offset'))):
                return True
    return False


def _copied_tables(image, context, check):
    """Pair a copied B1 graph with the sample address passed to its relocator."""
    read = context.get('read_code')
    if read is None:
        return {}
    functions = {}
    for fn in context.get('functions', ()):
        check()
        if (start := fn.get('rom_offset')) is not None and 0 <= start < start+fn['size'] <= len(image):
            functions.setdefault(fn['vram'], []).append(fn)
    relocators, transfers, pi_transfers = set(), set(), set()
    for pc, rows in functions.items():
        if len(rows) != 1 or not 0x70 <= rows[0]['size'] <= 0x280:
            continue
        start, size = rows[0]['rom_offset'], rows[0]['size']
        code = image[start:start+size]
        words = [word for word, in struct.iter_unpack('>I', code[:len(code)//4*4])]
        if _guards_b1(words):
            relocators.add(pc)
        if all(word in words for word in (
                0x00809021, 0x00a08821, 0x00c08021, 0xafb00014, 0x02403821, 0xafb10010)):
            transfers.add(pc)
        if all(word in words for word in (
                0x8fa40028, 0x8fa8002c, 0xa6020000, 0xae07000c, 0xae040008, 0xae080010)):
            pi_transfers.add(pc)
    if not relocators or not (transfers or pi_transfers):
        return {}
    needles = [struct.pack('>I', 0x0c000000 | ((pc >> 2) & 0x3ffffff)) for pc in relocators]
    result, wrappers = {}, set()
    for rows in functions.values():
        check()
        if len(rows) != 1 or rows[0]['size'] > 0x8000:
            continue
        fn = rows[0]
        start = fn['rom_offset']
        code = image[start:start+fn['size']]
        if not any(needle in code for needle in needles):
            continue
        events = read(fn['vram'], code, gp=context.get('gp', 0), check=check)['events']
        if pi_transfers and _forwarded_control(events, pi_transfers, relocators):
            wrappers.add(fn['vram'])
        loads = {e['instruction']: e for e in events if e['kind'] == 'load' and e['width'] == 4}
        calls = [e for e in events if e['kind'] == 'call']
        for copy, link in itertools.pairwise(calls):
            if (copy['target'] not in transfers or link['target'] not in relocators
                    or copy['block'] != link['block']
                    or not 0 < link['instruction']-copy['instruction'] <= 48):
                continue
            source, buffer, length = copy['args'][:3]
            used, table = link['args'][:2]
            if not (source and source['kind'] == 'constant' and length and length['kind'] == 'constant'
                    and buffer and used and used['kind'] == 'memory' and table and table['kind'] == 'constant'):
                continue
            control, base = source['value']-0xb0000000, table['value']-0xb0000000
            size = length['value']
            if not (0 <= control < control+size <= len(image) and 0 <= base < len(image)
                    and image[control:control+2] == b'B1'):
                continue
            load = loads.get(used['value'])
            place = load and load['place']
            if not place or place['kind'] != 'constant' or not copy['instruction'] < load['instruction'] < link['instruction']:
                continue
            if not any(e['place']['kind'] == 'constant' and e['place']['value'] == place['value']
                       and all(e['value'].get(k) == buffer.get(k) for k in ('kind', 'value', 'offset'))
                       for e in copy.get('memory', ())):
                continue
            result.setdefault(control, {}).setdefault(base, []).append(dict(
                function=fn['name'], instruction=link['instruction'], control_size=size,
                role='sample-table argument', reason='The B1 relocator receives the copied controls and the sample-table address.'))
    if wrappers:
        needles = [struct.pack('>I', 0x0c000000 | ((pc >> 2) & 0x3ffffff)) for pc in wrappers]
        for rows in functions.values():
            check()
            if len(rows)!=1 or rows[0]['size']>0x8000:
                continue
            fn = rows[0]
            start = fn['rom_offset']
            code = image[start:start+fn['size']]
            if not any(needle in code for needle in needles):
                continue
            for call in read(fn['vram'],code,gp=context.get('gp',0),check=check)['events']:
                if call['kind'] != 'call' or call['target'] not in wrappers or len(call['args']) < 4:
                    continue
                source, length, _, table = call['args'][:4]
                if not all(arg and arg['kind']=='constant' for arg in (source,length,table)):
                    continue
                control, base = source['value']-0xb0000000, table['value']-0xb0000000
                size = length['value']
                if (0 <= control < control+size <= len(image) and 0 <= base < len(image)
                        and image[control:control+2]==b'B1'):
                    result.setdefault(control,{}).setdefault(base,[]).append(dict(
                        function=fn['name'],instruction=call['instruction'],control_size=size,role='sample-table argument',
                        reason='The wrapper forwards the controls and wave address to their verified consumers.'))
    return result


def _fits(image, info, base, budget, check):
    """Validate every frame selector, not a statistical sample of high-entropy bytes."""
    for sample in info['samples']:
        start=base+sample['relative_offset'];end=start+sample['size']
        if start<base or end>len(image):return False
        if start<info['offset']+info['size'] and end>info['offset']:return False
        if sample['codec']=='N64 VADPCM':
            if any(image[start+sample['encoded_size']:end]):return False
            for at in range(start,start+sample['encoded_size'],9):
                if not budget[0]:return False
                budget[0]-=1
                if at%4096<9:check()
                if (image[at]&15)>=sample['predictors']:return False
        elif not info.get('corroborated'):return False
    return True


def _candidates(image):
    for hit in re.finditer(rb'B1\x00[\x01-\x80]',image):
        offset=hit.start()
        if offset+8>len(image):continue
        count=int.from_bytes(image[offset+2:offset+4],'big')
        relocated=offset>=len(B1_WRAPPER) and image[offset-len(B1_WRAPPER):offset]==B1_WRAPPER
        first=int.from_bytes(image[offset+4:offset+8],'big')
        if relocated:first-=RELOCATED_BASE+len(B1_WRAPPER)
        if not 4+count*4<=first<=MAX_CONTROL or first%4 or offset+first+12>len(image):continue
        header=image[offset+first:offset+first+12]
        if header[2]!=int(relocated) or header[3] or not 1000<=int.from_bytes(header[4:8],'big')<=192000:continue
        yield offset,relocated


def _uv_tables(image, check):
    """Read a B1 control and wave table paired by their UV sound FORM."""
    tables = {}
    matches = re.finditer(rb'FORM.{4}UV(?:SX|MB)', image, re.S)
    for match in itertools.islice(matches, MAX_CANDIDATES):
        check()
        offset = match.start()
        end = offset+8+int.from_bytes(image[offset+4:offset+8], 'big')
        if offset%2 or not offset+12 <= end <= len(image):
            continue
        at = offset+12
        chunks = []
        for _ in range(32):
            if at+8 > end:
                break
            tag, size = struct.unpack_from('>4sI', image, at)
            start = at+8
            at = start+size
            if at > end:
                break
            if tag != b'PAD ':
                chunks.append((tag, start, at))
            if len(chunks) > 2:
                break
        if at == end and [tag for tag, *_ in chunks] == [b'.CTL', b'.TBL']:
            _, control, control_end = chunks[0]
            _, wave, wave_end = chunks[1]
            if image[control:control+2] == b'B1':
                tables[control] = control_end, wave, wave_end, image[offset+8:offset+12], offset
    return tables


def regions(image, *, context=None, check=lambda: None, progress=lambda _: None):
    context=context or {};tables=loader_tables(image,context,check=check);results=[];budget=[MAX_HEADER_CHECKS]
    uv_tables = _uv_tables(image, check)
    candidates=list(itertools.islice(_candidates(image),MAX_CANDIDATES))
    copied = _copied_tables(image, context, check) if any(not relocated for _, relocated in candidates) else {}
    for number,(offset,relocated) in enumerate(candidates):
        check();progress(dict(phase='Recognizing audio banks',done=number,total=len(candidates)))
        sample_only = False
        try:
            info = bank(image, offset, relocated=relocated, check=check)
        except KeyMapError:
            if relocated:
                continue
            # Some sample banks leave MIDI key maps unset. Require independently
            # validated adjacent ADPCM data before advertising these as audio.
            try:
                info = bank(image, offset, sample_only=True, check=check)
            except BankError:
                continue
            if any(sample['codec'] != 'N64 VADPCM' for sample in info['samples']):
                continue
            sample_only = True
        except BankError:
            continue
        matched = {base:[ref for ref in refs if ref['control_size'] >= info['size']]
                   for base,refs in copied.get(offset, {}).items()}
        matched = {base:refs for base,refs in matched.items() if refs}
        loader_refs = tables | matched
        adjacent=(offset+info['size']+15)//16*16
        uv = uv_tables.get(offset) if not relocated else None
        if uv:
            control_end, wave, wave_end, _, _ = uv
            if (offset+info['size'] > control_end
                    or any(s['relative_offset']+s['size'] > wave_end-wave for s in info['samples'])):
                continue
            bases = [wave]
        elif relocated:
            # The wrapper relocates control pointers, while the sample offsets stay relative
            # to a separate, aligned table following the control graph.
            if min(sample['relative_offset'] for sample in info['samples']) != 0:
                continue
            for index,sample in enumerate(info['samples'],1):
                sample['label']=f'Sample {index}'
            info['offset']-=len(B1_WRAPPER)
            info['size']+=len(B1_WRAPPER)
            offset=info['offset']
            bases=[adjacent]
        elif sample_only:
            bases = [adjacent]
        else:
            bases=sorted(loader_refs,key=lambda at:(at not in matched,at!=adjacent,at))[:MAX_TABLE_PROBES] if loader_refs else [adjacent]
        fits=[]
        for base in bases:
            info['corroborated']=bool(uv) or base in loader_refs
            if _fits(image,info,base,budget,check):fits.append(base)
        if len(fits)!=1:
            if sample_only:
                continue
            # The control graph is useful even when table placement is unresolved.
            results.append(dict(offset=offset,size=info['size'],kind='audio',label='N64 sound-bank controls',confidence='validated',
                                reason='B1 control graph, envelopes, key maps, sample extents and predictor books passed. Sample-table placement is unresolved; no sample bytes are classified.',
                                media='audio',audio_kind='unresolved bank',sample_count=len(info['samples']),samples=[],
                                preview_settings=dict(format='auto',source='rom',offset=offset)))
            continue
        base=fits[0];confidence='validated' if uv or base in loader_refs else 'tentative'
        reason=(('Relocated B1 wrapper, control graph and every ADPCM frame selector passed. ' if relocated else
                 'B1 control graph and every ADPCM frame selector passed. ')+
                ('The UV sound FORM pairs the bounded control and wave chunks.' if uv else
                 'The loader copies this control graph and passes its sample-table address to the B1 relocator.' if base in matched else
                 'A named alBnkfNew call supplies the sample-table base.' if base in tables else
                 'Sample-table placement is inferred from adjacent aligned data; it is not confirmed by a named loader call.')+
                ' Static structure does not prove runtime use. Preview uses the bank nominal sample rate, without pitch, mixing or loop playback.')
        samples=[{**sample,'offset':base+sample['relative_offset']} for sample in info['samples']]
        common=dict(media='audio',audio_kind='sample bank',table_confidence=confidence,loader_refs=loader_refs.get(base,[]),table_offset=base)
        results.append(dict(offset=offset,size=info['size'],kind='audio',label='N64 sound-bank controls',confidence='validated',
                            reason=reason,preview_settings=dict(format='auto',source='rom',offset=offset),samples=samples,**common))
        seen=set()
        for sample in samples:
            key=sample['offset'],sample['size']
            if key in seen:continue
            seen.add(key)
            results.append(dict(offset=sample['offset'],size=sample['size'],kind='audio',label=sample['codec']+' sample',confidence=confidence,
                                reason=reason,preview_settings=dict(format='auto',source='rom',offset=sample['offset']),samples=[sample],**common))
    return results


def vadpcm(raw, coefficients, predictors, limit, *, check=lambda: None, bits=4):
    """Decode order-2 mono VADPCM using eight-sample vectors and signed Q11 books.

    Equations checked against vgmstream src/coding/vadpcm_decoder.c. This is a
    local preview, not a cycle-accurate audio microcode emulator.
    """
    if bits not in (2, 4):raise AssetError('The ADPCM frame width is unsupported.')
    frame_size = 1 + 2*bits
    if len(raw)%frame_size or len(coefficients)!=predictors*16:raise AssetError('The ADPCM frames or predictor book are incomplete.')
    midpoint = 1 << (bits-1)
    mask = 2*midpoint-1
    shifts = range(8-bits, -1, -bits)
    history=[0,0];out=[]
    for frame in range(min(len(raw)//frame_size,(limit+15)//16)):
        if frame%256==0:check()
        data=raw[frame*frame_size:(frame+1)*frame_size];shift=data[0]>>4;predictor=data[0]&15
        if predictor>=predictors:raise AssetError('An ADPCM frame selects a missing predictor.')
        book=coefficients[predictor*16:predictor*16+16]
        scale = 1 << (min(shift, 14) if bits == 2 else shift)
        codes = ((byte >> shift_by) & mask for byte in data[1:] for shift_by in shifts)
        residuals = [(code if code < midpoint else code-2*midpoint)*scale for code in codes]
        for group in (residuals[:8],residuals[8:]):
            decoded=[]
            for i in range(8):
                value=(group[i]<<11)+book[i]*history[0]+book[8+i]*history[1]
                value+=sum(book[8+k]*group[i-1-k] for k in range(i))
                decoded.append(max(-32768,min(32767,value>>11)))
            history=decoded[-2:];out.extend(decoded)
    return struct.pack('<'+str(min(limit,len(out)))+'h',*out[:limit])


def preview(image, asset, selection, *, book_image=None):
    if not asset.get('samples'):raise AssetError('The bank descriptors are valid, but sample-table placement is unresolved. Reimport with loader symbols or record the table evidence before previewing.')
    index=integer(selection.get('sample',0),'Sample',0,len(asset['samples'])-1);sample=asset['samples'][index]
    offset=sample['offset'];length=sample['size'];rate=sample['rate']
    if not 0<=offset<offset+length<=len(image):raise AssetError('The detected sample exceeds the current image. Refresh ROM Explorer.')
    limit=min(sample['samples'],rate*MAX_SECONDS,(MAX_BYTES-44)//2)
    raw=image[offset:offset+sample.get('encoded_size',length)]
    if sample['codec'] in ('N64 VADPCM', 'N64 VADPCM (2-bit)'):
        books=image if book_image is None else book_image
        at=sample['book_offset'];count=sample['predictors']*16
        if not 0<=at<at+count*2<=len(books):raise AssetError('The ADPCM predictor book exceeds the current image.')
        coefficients=struct.unpack_from('>'+str(count)+'h',books,at)
        pcm=vadpcm(raw,coefficients,sample['predictors'],limit,bits=sample.get('bits',4))
    else:pcm=b''.join(raw[i:i+2][::-1] for i in range(0,limit*2,2))
    output=io.BytesIO()
    with wave.open(output,'wb') as stream:stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(rate);stream.writeframes(pcm)
    return dict(media='audio',mime='audio/wav',data_url='data:audio/wav;base64,'+base64.b64encode(output.getvalue()).decode(),
                details=dict(format=sample['codec'],sample=index,rate=rate,channels=1,seconds=round(limit/rate,3),
                             original_samples=sample['samples'],truncated=limit<sample['samples'],note=asset['reason']),
                settings=dict(source='rom',format='auto',offset=asset['offset'],sample=index))
