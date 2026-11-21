"""Bounded reader for big-endian, grouped BOLT archives."""

import re
import struct
from dataclasses import dataclass
from itertools import pairwise

from ..formats import MAX_BYTES
from . import bolt_audio

ENTRY = struct.Struct('>4B3I')
MAX_MEMBERS = 4096
MAX_EXPANDED = 32*1024*1024


@dataclass(frozen=True)
class Member:
    kind: int
    offset: int
    end: int
    expanded: int
    stored: bool


def inflate(data, size):
    """Expand the literal and overlapping-copy commands in one member."""
    if not 0 < size <= MAX_BYTES:
        return None
    output = bytearray()
    cursor = 0
    length_bits = distance_bits = extensions = 0
    while cursor < len(data) and len(output) < size:
        byte = data[cursor]
        cursor += 1
        opcode = byte >> 4
        if opcode >= 9:
            extensions += 1
            if extensions > 6:
                return None
            if opcode >= 12:
                distance_bits = (distance_bits << 6) | (byte & 63)
            elif opcode >= 10:
                length_bits = (length_bits << 5) | (byte & 31)
            else:
                distance_bits, length_bits = (byte >> 2) & 3, byte & 3
            continue
        if opcode == 8:
            length = ((length_bits << 4) | (byte & 15))+1
            if cursor+length > len(data) or len(output)+length > size:
                return None
            output.extend(data[cursor:cursor+length])
            cursor += length
        else:
            distance = ((distance_bits << 4) | (byte & 15))+1
            length = ((length_bits << 3) | opcode)+extensions+2
            if distance > len(output) or len(output)+length > size:
                return None
            initial = output[-distance:]
            count, remainder = divmod(length,distance)
            output.extend(initial*count)
            output.extend(initial[:remainder])
        length_bits = distance_bits = extensions = 0
    return (bytes(output),cursor) if len(output) == size else None


def members(image, base):
    if base < 0 or base+16 > len(image) or image[base:base+4] != b'BOLT':
        return []
    hour, minute, second, _, month, day, _, groups = image[base+4:base+12]
    if hour > 23 or minute > 59 or second > 59 or not 1 <= month <= 12 or not 1 <= day <= 31:
        return []
    groups = groups or 256
    end = base+16+groups*ENTRY.size
    if end > len(image):
        return []
    output = []
    expanded = 0
    for flags, reserved_a, reserved_b, count, packed, relative, key in ENTRY.iter_unpack(image[base+16:end]):
        if flags not in (0,8) or any((reserved_a,reserved_b,key)) or not count or not packed or base+relative != end:
            return []
        table_start = end
        payload_start = table_start+count*ENTRY.size
        end = payload_start+packed
        if end > len(image) or len(output)+count > MAX_MEMBERS:
            return []
        records = list(ENTRY.iter_unpack(image[table_start:payload_start]))
        if base+records[0][5] != payload_start:
            return []
        terminator = (0,0,0,0,0,end-base,0)
        for record,following in pairwise([*records,terminator]):
            flags, reserved_a, reserved_b, kind, size, relative, key = record
            start, limit = base+relative, base+following[5]
            if (flags not in (0,8) or reserved_a or reserved_b or not key or not kind
                    or not 0 < size <= MAX_BYTES or not payload_start <= start < limit <= end
                    or flags and size > limit-start):
                return []
            expanded += size
            if expanded > MAX_EXPANDED:
                return []
            output.append(Member(kind,start,limit,size,bool(flags)))
    return output


def content(image, member):
    if member.stored:
        return image[member.offset:member.offset+member.expanded], member.expanded
    return inflate(image[member.offset:member.end],member.expanded)


def archives(image, check):
    for candidate in re.finditer(b'BOLT',image):
        check()
        if entries := members(image,candidate.start()):
            yield candidate.start(),entries


TEXTURE = 'bolt-texture'
MEMBER = 'bolt-member'


def texture_settings(member):
    # The RGBA pages are 32 pixels wide and contain one or two rows of
    # 32-pixel tiles. Four-bit sprites have separate dimension conventions.
    if member.kind == 8 and member.expanded in (2048,4096):
        return dict(format='rgba5551-be',width=32,height=member.expanded//64)
    if member.kind == 10 and member.expanded == 512:
        return dict(format='i4',width=32,height=32)
    return None


def regions(image, *, check=lambda: None, progress=lambda _: None):
    results = []
    for base, entries in archives(image,check):
        for index, member in enumerate(entries):
            if index%32 == 0:
                check()
                progress(dict(phase='Reading BOLT archive members',done=index,total=len(entries)))
            decoded = content(image,member)
            if decoded is None:
                continue
            data, used = decoded
            raw = dict(offset=member.offset,size=used,expanded_size=member.expanded,
                       archive_path=f'BOLT {base:08X}/Member {index+1}',member_storage='stored' if member.stored else 'BOLT LZSS')
            if settings := texture_settings(member):
                results.append(dict(**raw,kind='image',layout=TEXTURE,
                                    label=f'BOLT texture {index+1}',confidence='inferred',frames=1,palettes=0,levels=[],
                                    reason='The checked archive member uses a known texture record type and page length.',
                                    preview_settings=dict(**settings,source='rom',offset=member.offset)))
            elif model := model_region(raw,data,index,member.kind):
                results.append(model)
            elif member.stored and member.kind == 25 and (info := bolt_audio.voice(data)):
                results.append(dict(**raw,kind='audio',media='audio',layout=bolt_audio.VOX,confidence='validated',
                                    audio_kind='voice',label=f'BOLT audio {index+1}',
                                    samples=[dict(**info,offset=member.offset+12,label=f'Voice {index+1}')],
                                    reason='The BOLT voice header identifies a bounded mono Dialogic ADPCM sample.',
                                    preview_settings=dict(format='auto',source='rom',offset=member.offset)))
            else:
                results.append(dict(**raw,kind='container' if member.stored else 'compressed',layout=MEMBER,
                                    label=f'BOLT member {index+1} (type {member.kind})',confidence='validated',
                                    reason='The member fits its validated archive directory slot and expanded length.'))
    return results


def preview(image,asset,selection):
    from .. import formats

    start = asset['offset']
    packed = image[start:start+asset['size']]
    decoded = (packed,len(packed)) if asset['member_storage']=='stored' else inflate(packed,asset['expanded_size'])
    if decoded is None:
        raise formats.AssetError('The BOLT member does not decode. Scan the ROM again.')
    data = decoded[0]
    if asset['layout'] == MODEL:
        from . import display_meshes

        parts = mesh_parts(data,asset['member_type'])
        if not parts:
            raise formats.AssetError('The BOLT model changed. Scan the ROM again.')
        index = formats.integer(selection.get('mesh',0),'Mesh',0,len(parts)-1)
        lo,hi,_,_ = parts[index]
        result = display_meshes.preview(data,dict(offset=lo,size=hi-lo,address_maps=[(None,0)],
                                                   label=asset['label'],preview_settings={}),{})
    elif asset['layout'] == bolt_audio.VOX:
        result = bolt_audio.preview(data,asset)
    else:
        options = {**asset['preview_settings'],'offset':0}
        result = formats.preview(data,options)
    result['settings'] = dict(source='rom',format='auto',offset=start)
    if asset['layout'] == MODEL:
        result['settings']['mesh'] = index
    result['decoded'] = dict(codec=asset['member_storage'],bytes=len(decoded[0]),block_offset=start,member=asset['archive_path'])
    return result


MODEL = 'bolt-f3dex2'


def mesh_parts(data, kind):
    from .display_meshes import geometry

    table = {26:24,28:16}.get(kind)
    if table is None or len(data) < table+16 or int.from_bytes(data[4:8],'big') != len(data):
        return []
    vertices, count, commands, length = struct.unpack_from('>4I',data,table)
    end = commands+8*length
    if (vertices < table+16 or vertices%16 or not count or vertices+16*count != commands
            or not length or end > len(data)):
        return []
    parts = []
    start = commands
    for at in range(commands,end,8):
        word, address = struct.unpack_from('>II',data,at)
        if word>>24 == 1:
            amount = (word>>12)&255
            if address%16 or not vertices <= address < address+16*amount <= commands:
                return []
        if word != 0xdf000000 or address:
            continue
        if parsed := geometry(data,start,at+8,{None:0}):
            _, points, faces = parsed
            parts.append((start,at+8,len(points),len(faces)))
        start = at+8
    return parts


def model_region(raw, data, index, kind):
    parts = mesh_parts(data,kind)
    if not parts:
        return None
    return dict(**raw,media='model',kind='3d model',layout=MODEL,label=f'BOLT model {index+1}',
                confidence='validated',member_type=kind,
                vertices=sum(v for _,_,v,_ in parts),triangles=sum(t for *_,t in parts),
                meshes=[dict(name=f'Mesh {i+1}',vertices=v,triangles=t) for i,(_,_,v,t) in enumerate(parts)],
                reason='The member declares bounded vertex and display-list runs. Closed local lists resolve their triangle indices.',
                preview_settings=dict(format='auto',source='rom',offset=raw['offset']))
