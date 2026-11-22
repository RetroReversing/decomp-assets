"""Rigid legacy object meshes and textures from relocatable resources."""
import re
import struct

from .. import formats
from . import reloc_level_objects

MODEL = 'legacy-reloc-object-meshes'
IMAGE = 'legacy-reloc-object-textures'


def meshes(data):
    if len(data)<8:return []
    n=struct.unpack_from('>I',data)[0]
    base=4+4*n
    if not 1<=n<=65536 or base+0x30>len(data):return []
    offsets=struct.unpack_from(f'>{n}I',data,4)
    relocs=set(offsets)
    if len(relocs)!=n or any(x%4 or base+x+4>len(data) for x in offsets):return []
    def word(at):return struct.unpack_from('>I',data,base+at)[0]
    count,animations=struct.unpack_from('>HH',data,base+8)
    if animations or not 1<=count<=64 or 0xc not in relocs:return []
    table=word(0xc)
    if table%4 or base+table+4*count>len(data):return []
    result=[]
    for i in range(count):
        if table+4*i not in relocs:continue
        at=word(table+4*i)
        if at%4 or base+at+0x34>len(data) or at+4 not in relocs or at+0x14 not in relocs:continue
        nv,vertex,nf,face,parts=word(at),word(at+4),word(at+0x10),word(at+0x14),word(at+0x18)
        if not 3<=nv<=16384 or not 1<=nf<=32768 or parts!=1:continue
        if vertex%2 or face%2 or base+vertex+12*nv>len(data) or base+face+12*nf>len(data):continue
        points=[struct.unpack_from('>3h',data,base+vertex+12*j) for j in range(nv)]
        faces=[struct.unpack_from('>3H',data,base+face+12*j) for j in range(nf)]
        if any(max(f)>=nv or len(set(f))<3 for f in faces):continue
        pool=word(at+0x30) if at+0x30 in relocs else 0
        result.append(dict(offset=at,vertices=points,faces=faces,pool=base+pool if pool else 0))
    return result


def textures(data,found):
    pools={x['pool'] for x in found if x['pool']}
    if len(pools)!=1:return []
    pool=pools.pop()
    result,seen=[],set()
    for match in re.finditer(b'\xe7\x00\x00\x00\x00\x00\x00\x00',data):
        at=match.start()
        if at+0x68>len(data):continue
        c=[struct.unpack_from('>II',data,at+8*j) for j in range(13)]
        if ([x[0]>>24 for x in c]!=[0xe7,0xba,0xfd,0xf5,0xf0,0xf5,0xe6,0xfd,0xf3,0xf5,0xf2,0xe6,0xb8]
                or c[2][0]!=0xfd100000 or c[7][0]!=0xfd500000 or c[2][1]>>24!=5 or c[7][1]>>24!=5
                or c[10][0]!=0xf2000000 or c[10][1]&0x003003):continue
        palette,pixels=pool+(c[2][1]&0xffffff),pool+(c[7][1]&0xffffff)
        tile=c[10][1];width,height=((tile>>12)&0xfff)//4+1,(tile&0xfff)//4+1
        size=(width*height+1)//2;key=(palette,pixels,width,height)
        if (key in seen or not 1<=width<=256 or not 1<=height<=256 or not 0<=palette<=len(data)-32
                or not 0<=pixels<=len(data)-size or not any(data[palette:palette+32])):continue
        seen.add(key)
        result.append(dict(offset=pixels,format='ci4',width=width,height=height,
                           palette_offset=palette,palette_format='rgba5551-be'))
    return result


def regions(image, *, check=lambda: None, **kwargs):
    result=[]
    for row in reloc_level_objects.members(image):
        check()
        try:data=reloc_level_objects.unpack(image,row)
        except formats.AssetError:continue
        found=meshes(data)
        if not found:continue
        name=row['name'].decode('ascii').rstrip('_')
        items=textures(data,found)
        if items:
            listed=[dict(label=f'Texture {i+1}',width=x['width'],height=x['height'],frames=1,palettes=1,
                         palette_entries=[16],levels=[dict(width=x['width'],height=x['height'],offset=0)],preview_settings=x)
                    for i,x in enumerate(items)]
            result.append(dict(offset=row['start'],size=row['end']-row['start'],kind='image',media='image',layout=IMAGE,
                               confidence='validated',label=name+' textures',textures=listed,texture_count=len(listed),frames=1,
                               reason='Relocated texture pools and material commands bound CI4 pixels and palette.',
                               preview_settings=dict(format='auto',source='rom',offset=row['start'],texture=0)))
        listed=[dict(label=f'Mesh {i+1}',vertices=len(x['vertices']),triangles=len(x['faces']),offset=x['offset'])
                for i,x in enumerate(found)]
        result.append(dict(offset=row['start'],size=row['end']-row['start'],kind='3d model',media='model',layout=MODEL,
                           confidence='validated',label=name+' object',meshes=listed,nodes=len(listed),
                           triangles=sum(x['triangles'] for x in listed),
                           reason='Relocations and rigid mesh bounds resolve every vertex and face index.',
                           preview_settings=dict(format='auto',source='rom',offset=row['start'],mesh=0)))
    return result


def preview(image,asset,selection):
    data=reloc_level_objects.unpack(image,dict(start=asset['offset'],end=asset['offset']+asset['size']))
    found=meshes(data)
    if not found:raise formats.AssetError('The object bank changed. Rescan ROM Explorer.')
    if asset['layout']==IMAGE:
        rows=textures(data,found)
        if not rows:raise formats.AssetError('The object textures changed. Rescan ROM Explorer.')
        index=formats.integer(selection.get('texture',0),'Texture',0,len(rows)-1)
        result=formats.preview(data,rows[index]);result['settings']=dict(asset['preview_settings'],texture=index)
        result['details']['note']=asset['reason'];return result
    index=formats.integer(selection.get('mesh',0),'Mesh',0,len(found)-1)
    vertices=[(x,z,-y) for x,y,z in found[index]['vertices']];faces=found[index]['faces']
    edges={tuple(sorted((f[i],f[(i+1)%3]))) for f in faces for i in range(3)}
    return dict(media='model',vertices=vertices,triangles=len(faces),edges=sorted(edges),
                points=sorted({i for f in faces for i in f}),
                surfaces=[dict(indices=f,uv=[[0,0]]*3,colors=[[255,255,255,255]]*3,material=0) for f in faces],
                materials=[],details=dict(format='Rigid legacy object',vertices=len(vertices),triangles=len(faces)),
                note='Local rigid geometry; textures and placement are separate.',
                settings=dict(asset['preview_settings'],mesh=index))
