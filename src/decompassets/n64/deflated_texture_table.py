"""Indexed textures described by a size table inside a raw-deflate program.

The table holds eight-byte records ending with a sentinel; a code constant gives
its cartridge data base. Only individually bounded, palette-indexed deflate
images whose decoded size and indices agree with their headers are previewed.
"""
import re
import struct
import zlib

from .. import formats

LAYOUT = 'deflated-table-texture'
MAX_STREAM = 2 * 1024 * 1024


def image(data):
    if len(data) < 8 or not data[0] & 0x40 or data[1] not in (9,10,11,12):return None
    fmt, count = data[1], data[2] + 1
    pos = 3 + count * 2
    if pos + 4 > len(data):return None
    w, h = data[pos:pos+2]
    if not w or not h or w*h > 65536:return None
    magic = data[pos+2:pos+4]
    skip = 2 if magic == b'\x11\x72' else 5 if magic == b'\x11\x73' else 0
    if not skip or pos+2+skip >= len(data):return None
    four = fmt in (10,12)
    if count > (16 if four else 256):return None
    stride = (w+1)//2 if four else w
    try:
        stream=zlib.decompressobj(-15)
        pixels=stream.decompress(data[pos+2+skip:], stride*h+1)
    except zlib.error:return None
    if not stream.eof or len(pixels) != stride*h:return None
    for y in range(h):
        for x in range(w):
            n=pixels[y*stride+x//2] >> (0 if x&1 else 4) & 15 if four else pixels[y*stride+x]
            if n>=count:return None
    # The engine stores the rows bottom first.
    pixels=b''.join(pixels[y*stride:(y+1)*stride] for y in range(h-1,-1,-1))
    palette=data[3:pos] + bytes(((16 if four else 256)-count)*2)
    return pixels+palette,dict(format='ci4' if four else 'ci8',width=w,height=h,offset=0,
                               palette_offset=len(pixels),palette_format='rgba5551-be' if fmt in (9,10) else 'ia16')


def constants(rom):
    result=set();end=min(len(rom),2*1024*1024)&~3
    for at in range(0,end-32,4):
        a=struct.unpack_from('>I',rom,at)[0]
        if a>>26!=15 or not (reg:=(a>>16)&31):continue
        for off in range(at+4,at+32,4):
            b=struct.unpack_from('>I',rom,off)[0];op=b>>26
            if op not in (9,13) or (b>>21)&31 != reg:continue
            low=b&0xffff
            value=((a&0xffff)<<16)+(low-0x10000 if op==9 and low&0x8000 else low)
            if 0x100000 < value < len(rom):result.add(value)
    return result


def tables(rom, check=lambda:None):
    at=0
    while (at:=rom.find(b'\x11\x72',at))>=0:
        check()
        try:
            stream=zlib.decompressobj(-15)
            data=stream.decompress(rom[at+2:at+0x50000],MAX_STREAM+1)
        except zlib.error:at+=2;continue
        if stream.eof and len(data)<=MAX_STREAM:
            for m in re.finditer(b'\0\0\xff\xff\0\0\0\0',data):
                end=m.start();pos=end;sizes=[]
                while pos>=8:
                    first,flags=struct.unpack_from('>II',data,pos-8);size=first&0xffffff
                    if not 1<=size<=4096 or flags&0xffff:break
                    sizes.append(size);pos-=8
                if len(sizes)>=128:yield at,pos,list(reversed(sizes))
        at+=2


def regions(rom, *, check=lambda:None, **kwargs):
    result=[];bases=constants(rom)
    for source,table,sizes in tables(rom,check):
        total=sum(sizes)
        candidates=[]
        for base in bases:
            if base+total>len(rom):continue
            at=base;hits=0
            for size in sizes[:32]:
                if image(rom[at:at+size]):hits+=1
                at+=size
            if hits>=3:candidates.append(base)
        if len(candidates)!=1:continue
        at=candidates[0]
        for index,size in enumerate(sizes):
            check();found=image(rom[at:at+size])
            if found:
                _, settings=found
                result.append(dict(offset=at,size=size,kind='image',media='image',layout=LAYOUT,
                    confidence='validated',label=f'Indexed texture {index}',table=table,stream=source,
                    levels=[dict(width=settings['width'],height=settings['height'],offset=0)],frames=1,palettes=1,
                    preview_settings=dict(format='auto',source='rom',offset=at),
                    reason='A bounded size table and code-derived data base locate a validated indexed image.'))
            at+=size
    return result


def preview(rom, asset, selection):
    found=image(rom[asset['offset']:asset['offset']+asset['size']])
    if not found:raise formats.AssetError('The indexed image changed. Rescan ROM Explorer.')
    data,settings=found
    result=formats.preview(data,settings)
    result['settings']=dict(format='auto',source='rom',offset=asset['offset'])
    result['details']['note']=asset['reason']
    return result
