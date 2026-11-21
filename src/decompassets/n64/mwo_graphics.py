"""Preview graphics named by raw overlay display lists and their packed DMA loads."""

import struct
from itertools import pairwise

from .. import formats
from . import display_lists, display_meshes, textures

TEXTURES = 'mwo-packed-textures'
MODELS = 'mwo-packed-models'
RAM = 0x80000000


def inflate(data):
    """Decode one LZSS block; its header counts tokens, including whole copies."""
    if len(data) < 7 or data[0] != 1:
        return None
    tokens = int.from_bytes(data[1:5],'big')
    if not 0 < tokens <= len(data)-6:
        return None
    window = bytearray(4096)
    write, cursor, flags = 0xfee, 5, 0
    output = bytearray()
    for token in range(tokens):
        if token%8 == 0:
            if cursor >= len(data):
                return None
            flags = data[cursor]
            cursor += 1
        if flags&1:
            if cursor >= len(data):
                return None
            value = data[cursor]
            cursor += 1
            output.append(value)
            window[write] = value
            write = (write+1)&4095
        else:
            if cursor+2 > len(data):
                return None
            low, high = data[cursor:cursor+2]
            cursor += 2
            source = low|((high&240)<<4)
            for index in range((high&15)+3):
                value = window[(source+index)&4095]
                output.append(value)
                window[write] = value
                write = (write+1)&4095
        flags >>= 1
        if len(output)>formats.MAX_BYTES:
            return None
    return bytes(output),cursor


def _mapped(address, size, segments, owner):
    candidates = [s['rom_start']+address-s['vram'] for s in segments
                  if s['vram']<=address and address+size<=s['vram']+s['rom_end']-s['rom_start']]
    local = owner['rom_start']+address-owner['vram']
    if local in candidates and owner['rom_start']<=local<=owner['rom_end']-size:
        return local
    return candidates[0] if len(candidates)==1 else None


def _argument(event,index):
    args = event.get('args',())
    arg = args[index] if index<len(args) else None
    return arg['value'] if arg and arg['kind']=='constant' else None


def loads(image, context, check):
    segments = context.get('segments',())
    read = context.get('read_code')
    if not read:
        return
    owners = [s for s in segments if image[max(s['rom_start']-64,0):s['rom_start']-60]==b'MWo2']
    if not owners:
        return
    seen = set()
    decoded_bytes = 0
    for fn in context.get('functions',()):
        check()
        at, size = fn.get('rom_offset'), fn['size']
        if at is None or not 0 < size <= 0x8000:
            continue
        owner = next((s for s in owners if s['rom_start']<=at<at+size<=s['rom_end']),None)
        if owner is None:
            continue
        events = [e for e in read(fn['vram'],image[at:at+size],gp=context.get('gp',0),check=check)['events']
                  if e['kind']=='call']
        for load, decode in pairwise(events):
            if load['block']!=decode['block'] or not 0<decode['instruction']-load['instruction']<=64:
                continue
            pointer, staging, destination = _argument(load,0), _argument(decode,0), _argument(decode,1)
            if pointer is None or staging is None or destination is None or not RAM <= destination < RAM+0x800000:
                continue
            descriptor = _mapped(pointer,12,segments,owner)
            decoder = _mapped(decode['target'],32,segments,owner)
            if descriptor is None or decoder is None:
                continue
            # The dispatcher reads its mode byte and bounds the jump-table selector.
            code = image[decoder:decoder+32]
            if b'\x90\x87\x00\x00' not in code or b'\x2c\xe1\x00\x0a' not in code:
                continue
            ram, start, end = struct.unpack_from('>3I',image,descriptor)
            if (ram!=staging or not 0 < start < end <= len(image)
                    or end-start>formats.MAX_BYTES or (start,destination) in seen):
                continue
            if not (decoded := inflate(image[start:end])):
                continue
            data, used = decoded
            if destination+len(data)>RAM+0x800000 or any(image[start+used:end]):
                continue
            decoded_bytes += len(data)
            if decoded_bytes>32*1024*1024:
                return
            seen.add((start,destination))
            yield owner,start,used,destination-RAM,data


def texture_items(image,group,data,base):
    results = {}
    for found in display_lists._textures(image,group):
        offset = found['address']-base
        if found['space']!=128 or not 0<=offset<=len(data)-found['bytes']:
            continue
        width,height = found['width'],found['height']
        if found['swapped'] and (found['bytes']//height)%8:
            continue
        options = dict(format=found['fmt'],width=width,height=height,offset=offset)
        palette, palette_entries = [], []
        if 'palette_address' in found:
            color = found['palette_address']-base
            entries = found['palette_entries']
            if found['palette_space']!=128 or not 0<=color<=len(data)-2*entries:
                continue
            if found['fmt']=='ci8' and max(data[offset:offset+found['bytes']])>=entries:
                continue
            options.update(palette_offset=color,palette_format=found['palette_format'])
            palette.append(color)
            palette_entries.append(entries)
        key = tuple(options.values())
        results.setdefault(key,dict(preview_settings=options,frames=1,palettes=len(palette),
                                    palette_offsets=palette,palette_entries=palette_entries,
                                    levels=[dict(width=width,height=height,offset=0)],
                                    swapped=found['swapped'],texel_bytes=found['bytes']))
        if len(results)>=512:
            break
    return results.values()


def _geometry(image, data, base, start, end):
    commands = image[start:end]
    if len(commands)%8 or not 0<len(commands)<=0x8000:
        return None
    for word,address in struct.iter_unpack('>II',commands):
        count = display_lists._vertex_count(word)
        if count and not RAM+base<=address<=RAM+base+len(data)-16*count:
            return None
    offset = (len(data)+7)&~7
    combined = data+bytes(offset-len(data))+commands
    result = display_meshes.geometry(combined,offset,len(combined),{128:-base})
    return (combined,offset,result) if result else None


def mesh_items(image, group, owner, data, base, pointers):
    starts = display_lists._starts(image,group)
    end = min(owner['rom_end'],group['end']+96)&~7
    displacement = owner['vram']-owner['rom_start']
    items = []
    for start,stop in pairwise([*starts,end]):
        if start+displacement not in pointers:
            continue
        if result := _geometry(image,data,base,start,stop):
            _,_,(_,vertices,faces) = result
            items.append(dict(name=f'Mesh {len(items)+1}',start=start,end=stop,
                              vertices=len(vertices),triangles=len(faces)))
    return items


def regions(image, *, context=None, check=lambda:None, progress=lambda _:None):
    banks = list(loads(image,context or {},check))
    if not banks:
        return []
    vertices, commands = display_lists._commands(image,check)
    groups = display_lists._files(vertices,commands)
    pointers = {word for word, in struct.iter_unpack('>I',image[:len(image)//4*4]) if RAM <= word < RAM+0x800000}
    results = []
    for number,(owner,start,used,base,data) in enumerate(banks):
        check()
        progress(dict(phase='Checking packed graphics banks',done=number,total=len(banks)))
        evidence = display_lists._Evidence(data,check)
        textures, meshes = {}, []
        for group in groups:
            if not owner['rom_start']<=group['start']<group['end']<=owner['rom_end']:
                continue
            refs = {(address,count) for _,space,address,count in group['vertices'] if space==128}
            if sum(evidence.fits([ref],-base) for ref in refs)<2:
                continue
            for item in texture_items(image,group,data,base):
                textures.setdefault(tuple(item['preview_settings'].values()),item)
            meshes.extend(mesh_items(image,group,owner,data,base,pointers))
        shared = dict(offset=start,size=used,expanded_size=len(data),ram_base=base,confidence='validated',
                      reason='A verified loader tuple supplies the packed bytes; display commands corroborate the decoded destination.')
        if textures:
            items = list(textures.values())
            results.append(dict(**shared,kind='image',layout=TEXTURES,label='Packed overlay textures',
                                frames=1,palettes=items[0]['palettes'],levels=items[0]['levels'],textures=items,
                                preview_settings=dict(**(items[0]['preview_settings'] | {'offset':start}),source='rom')))
        if meshes:
            results.append(dict(**shared,kind='3d model',media='model',layout=MODELS,label='Packed overlay models',
                                meshes=meshes,vertices=sum(m['vertices'] for m in meshes),
                                triangles=sum(m['triangles'] for m in meshes),
                                preview_settings=dict(format='auto',source='rom',offset=start)))
    return results


def preview(image, asset, selection):
    start = asset['offset']
    packed = inflate(image[start:start+asset['size']])
    if not packed:
        raise formats.AssetError('The packed graphics block changed. Scan ROM Explorer again.')
    data,_ = packed
    if asset['layout']==TEXTURES:
        index = formats.integer(selection.get('texture',0),'Texture',0,len(asset['textures'])-1)
        item = asset['textures'][index]
        options = item['preview_settings']
        if item['swapped']:
            offset = options['offset']
            row = item['texel_bytes']//options['height']
            pixels = bytearray(data[offset:offset+item['texel_bytes']])
            for line in range(row,len(pixels),2*row):
                for word in range(line,line+row,8):
                    pixels[word:word+8] = pixels[word+4:word+8]+pixels[word:word+4]
            data = data[:offset]+pixels+data[offset+len(pixels):]
        result = textures.preview(data,{**item,'offset':start,'reason':asset['reason']},{})
        result['settings'] = dict(source='rom',format='auto',offset=start,texture=index)
    else:
        index = formats.integer(selection.get('mesh',0),'Mesh',0,len(asset['meshes'])-1)
        item = asset['meshes'][index]
        if not (geometry := _geometry(image,data,asset['ram_base'],item['start'],item['end'])):
            raise formats.AssetError('The packed model changed. Scan ROM Explorer again.')
        combined,offset,_ = geometry
        settings = dict(source='rom',format='auto',offset=start,mesh=index)
        result = display_meshes.preview(combined,dict(offset=offset,size=len(combined)-offset,
                                        label=asset['label'],address_maps=[(128,-asset['ram_base'])],
                                        preview_settings=settings),{})
    result['decoded'] = dict(codec='LZSS',bytes=len(data),block_offset=start,member=asset['label'])
    return result
