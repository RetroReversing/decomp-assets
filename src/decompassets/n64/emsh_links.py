"""Resolve local effect texture IDs through checked resource and effect tables."""

import itertools
import re
import struct

ROW = struct.Struct('>III')
EFFECT = struct.Struct('>IHHI')
MESH_LISTS = re.compile(rb'(?:\x00[\x01-\x7f]..\x00[\x01-\x20]\0\0\x80...){8,512}', re.S)
TEXTURE_IDS = re.compile(rb'(?:\0{10}(?:\0[\x00-\xfe]|\xff\xff)){8,512}')
MAX_DIRECTORY_ROWS = 2048
MIN_LINKS = 8


def _directory(image, root):
    if not 0<=root<=len(image)-ROW.size or root%4:
        return None
    table_size=ROW.unpack_from(image,root)[0]
    count,remainder=divmod(table_size,ROW.size)
    if remainder or not 2<=count<=MAX_DIRECTORY_ROWS or root+table_size>=len(image):
        return None
    offsets=[]
    expected=root+table_size
    for index in range(count):
        relative,size,checksum=ROW.unpack_from(image,root+index*ROW.size)
        at=root+relative
        if at!=expected or at+18>len(image) or not 0<size<=4*1024*1024 or not 0<=checksum<=size*255:
            return None
        marker=image[at:at+4]
        if marker==b'RNC\1':
            expanded,=struct.unpack_from('>I',image,at+4)
            if expanded!=size:
                return None
            packed,stored_sum=struct.unpack_from('>II',image,at+8)
            if packed<2 or stored_sum!=checksum:
                return None
            end=at+18+packed
            trailer=(end+3)&~3
            if image[trailer:trailer+4]==bytes(4):
                trailer+=4
            if any(image[end:trailer]) or image[trailer:trailer+4]!=b'END!':
                return None
            expected=trailer+4
        elif marker==b'RNX\1' and index+1<count:
            # Chained payloads may occur between the independently checked entries.
            next_relative,=struct.unpack_from('>I',image,root+(index+1)*ROW.size)
            expected=root+next_relative
            if expected<=at+18 or expected%4:
                return None
        else:
            return None
        if expected>len(image):
            return None
        offsets.append(at)
    return offsets


def _directories(image,banks,check):
    roots={}
    attempted=set()
    for bank in itertools.islice(banks,32):
        check()
        offset=bank['offset']
        header=image[offset+4:offset+16]
        if len(header)!=12:
            continue
        size,_,checksum=ROW.unpack(header)
        needle=struct.pack('>II',size,checksum)
        lo=max(4,offset-32*1024*1024)
        for _ in range(32):
            at=image.find(needle,lo,offset)
            if at<0:
                break
            lo=at+1
            relative,=struct.unpack_from('>I',image,at-4)
            root=offset-relative
            if root in attempted or not 0<=root<=at-4 or (at-4-root)%ROW.size:
                continue
            attempted.add(root)
            if offsets:=_directory(image,root):
                roots[root]=offsets
    return roots


def _mesh_groups(image,check):
    for match in itertools.islice(MESH_LISTS.finditer(image),128):
        check()
        table=match.start()
        records=list(EFFECT.iter_unpack(match[0]))
        span=sum((count*2+3)&~3 for _,count,_,_ in records)
        cursor=table-span
        if cursor<0 or table%4:
            continue
        delta=cursor-records[0][0]
        groups=[]
        for pointer,count,_,_ in records:
            if pointer+delta!=cursor:
                break
            end=cursor+count*2
            aligned=(end+3)&~3
            if any(image[end:aligned]):
                break
            groups.append(struct.unpack_from(f'>{count}H',image,cursor))
            cursor=aligned
        if cursor==table:
            yield table,groups


def link(image,assets,check=lambda:None):
    """Attach only unambiguous links corroborated by both effect tables."""
    by_offset={asset['offset']:asset for asset in assets if asset.get('layout') in
               ('rnc-sum32-texture-bank','emsh-v010')}
    banks=[asset for asset in by_offset.values() if asset['layout']=='rnc-sum32-texture-bank']
    if not banks or len(banks)==len(by_offset):
        return
    directories=_directories(image,banks,check)
    if not directories:
        return
    tables=[]
    for match in itertools.islice(TEXTURE_IDS.finditer(image),128):
        check()
        ids=[value[0] for value in struct.iter_unpack('>10xh',match[0])]
        if match.start()%4==0 and len(set(ids)-{-1})>=MIN_LINKS:
            tables.append((match.start(),ids))
    matches=[]
    for group_at,groups in _mesh_groups(image,check):
        for root,entries in directories.items():
            check()
            if any(max(group)>=len(entries) for group in groups):
                continue
            for texture_at,ids in tables:
                if len(ids)<len(groups) or max(ids[:len(groups)])>=len(entries):
                    continue
                links={}
                for group,texture_id in zip(groups,ids):
                    bank=by_offset.get(entries[texture_id]) if texture_id>=0 else None
                    for mesh_id in group:
                        model=by_offset.get(entries[mesh_id])
                        if model and model['layout']=='emsh-v010':
                            links.setdefault(model['offset'],set()).add(bank['offset'] if bank else None)
                linked={offset:next(iter(targets)) for offset,targets in links.items() if len(targets)==1 and None not in targets}
                usable={offset:target for offset,target in linked.items()
                        if by_offset[target]['layout']=='rnc-sum32-texture-bank' and
                        any(index<len(by_offset[target]['textures']) for index in by_offset[offset]['texture_ids'])}
                if len(usable)>=MIN_LINKS and len(set(usable.values()))>=MIN_LINKS:
                    matches.append((usable,root,group_at,texture_at))
    if len(matches)!=1:
        return
    linked,root,groups,textures=matches[0]
    for offset,target in linked.items():
        by_offset[offset]['emsh_texture_bank']=dict(offset=target,directory=root,mesh_table=groups,texture_table=textures)
