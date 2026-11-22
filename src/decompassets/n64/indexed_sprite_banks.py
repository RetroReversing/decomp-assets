"""Indexed sprites with relative frame offsets and per-frame palettes."""
import struct

from .. import formats

LAYOUT = 'indexed-sprite-bank'


def bank(rom, at):
    if at<0 or at+52>len(rom):return None
    values=struct.unpack_from('>8I',rom,at);_,pal,anim,mapping,index,*_=values
    if values[0] or not (0<pal<anim<mapping<index<=at and index-pal<0x800000):return None
    base=at-index
    if rom[base:base+3]!=b'46d' or rom[base+mapping:base+mapping+4]!=b'46d\0':return None
    section=base+pal; first=struct.unpack_from('>I',rom,section)[0]
    if not 8<=first<=1024 or first%4 or section+first+4>len(rom):return None
    count=first//4
    offsets=struct.unpack_from(f'>{count}I',rom,section)
    if rom[section+first:section+first+4]!=b'46d\0':return None
    table=at+32
    if rom[table:table+4]!=bytes(4):return None
    frames=[];previous=0;end=table
    for i in range(min(4096,(len(rom)-table)//4-1,mapping and index-mapping-4)):
        current,nxt=struct.unpack_from('>II',rom,table+i*4)
        if current<previous or nxt<current or nxt>pal:break
        previous=current;end=table+(i+2)*4
        if nxt==current or base+current+8>len(rom):continue
        magic,flag,w,h=struct.unpack_from('<3sBHH',rom,base+current)
        if magic!=b'46d' or flag not in (0,16) or not 0<w<=512 or not 0<h<=512:continue
        four=flag==16;need=((w+1)//2 if four else w)*h
        if 8+need>nxt-current:continue
        palette_id=rom[base+mapping+4+i]
        if palette_id+1>=count:continue
        p,q=offsets[palette_id:palette_id+2];colors=32 if four else 512
        if not first<=p<q<=anim-pal or q-p<colors+8:continue
        if rom[section+p:section+p+4]!=b'46d\0' or rom[section+q-4:section+q]!=b'\xff'*4:continue
        frames.append(dict(index=i,offset=base+current+8,width=w,height=h,format='ci4' if four else 'ci8',
                           palette_offset=section+p+4,size=need))
    if len(frames)<3:return None
    return base,end-base,frames


def regions(rom, *, check=lambda:None, **kwargs):
    result=[]
    for at in range(0,len(rom)-64,4):
        if at%0x10000==0:check()
        if rom[at:at+4]!=bytes(4):continue
        found=bank(rom,at)
        if not found:continue
        base,size,frames=found
        items=[dict(label=f'Frame {f["index"]+1}',size=f['size'],frames=1,palettes=1,
                    levels=[dict(width=f['width'],height=f['height'],offset=0)]) for f in frames]
        result.append(dict(offset=base,size=size,kind='image',media='image',layout=LAYOUT,confidence='validated',
            label=f'Sprite bank · {len(items)} frames',table=at,textures=items,texture_count=len(items),
            frames=1,palettes=1,levels=items[0]['levels'],preview_settings=dict(format='auto',source='rom',offset=base,texture=0),
            reason='A bounded frame index and palette mapping connect indexed sprites to their own colour tables.'))
    return result


def preview(rom,asset,selection):
    found=bank(rom,asset['table'])
    if not found or found[0]!=asset['offset']:raise formats.AssetError('The sprite bank changed. Rescan ROM Explorer.')
    index=formats.integer(selection.get('texture',0),'Texture',0,len(found[2])-1);frame=found[2][index]
    settings=dict(format=frame['format'],width=frame['width'],height=frame['height'],offset=frame['offset'],
                  palette_offset=frame['palette_offset'],palette_format='rgba5551-be')
    result=formats.preview(rom,settings);result['settings']=dict(format='auto',source='rom',offset=asset['offset'],texture=index)
    result['details'].update(texture=index,note=asset['reason']);return result
