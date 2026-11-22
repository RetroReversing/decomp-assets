"""Reconstruct bounded grid maps from indexed local tile meshes."""
import struct

from .. import formats

LAYOUT = 'grid-tile-mesh'


def tile(data,start,end):
    if data[start:start+4]!=b'46d\0' or start+8>end:return None
    y,_,_,count=data[start+4:start+8]
    if not 3<=count<=32 or start+8+count*3>end:return None
    vertices=[struct.unpack_from('>bBb',data,start+8+i*3) for i in range(count)]
    pos=start+8+count*3;faces=[]
    for _ in range(128):
        if pos>=end:return None
        flags=data[pos];pos+=1
        if flags&0x20:pos+=2
        pos+=3*(4 if flags&0x40 else 3) if flags&0x80 else 3
        triangles=2 if flags&0x40 else 1
        if pos+triangles*2>end:return None
        for _ in range(triangles):
            word=struct.unpack_from('<H',data,pos)[0];pos+=2
            face=((word>>10)&31,(word>>5)&31,word&31)
            if any(i>=count for i in face):return None
            faces.append(face)
        if flags&0x10:return y,vertices,faces
    return None


def geometry(rom,base):
    if base<0 or base+48>len(rom):return None
    grid,mesh,end=struct.unpack_from('>3I',rom,base)
    if grid!=0x30 or not grid<mesh<end<0x100000 or base+end>len(rom):return None
    if rom[base+grid:base+grid+4]!=b'46d\0':return None
    sx,sz,w,h=rom[base+grid+4:base+grid+8]
    if not 1<=sx<=128 or not 1<=sz<=128 or not 1<=w<=128 or not 1<=h<=128 or grid+12+w*h*2>mesh:return None
    start=base+mesh;first=struct.unpack_from('>I',rom,start)[0]
    if not 4<=first<=0x4000 or first%4 or mesh+first>=end:return None
    count=first//4;offsets=struct.unpack_from(f'>{count}I',rom,start)
    if any(a>b for a,b in zip(offsets,offsets[1:])) or offsets[-1]>end-mesh:return None
    refs=struct.unpack_from(f'<{w*h}H',rom,base+grid+12);used={x-1 for x in refs if x}
    if not used or max(used)>=count:return None
    tiles={i:tile(rom,start+offsets[i],start+(offsets[i+1] if i+1<count else end-mesh)) for i in used}
    if any(value is None for value in tiles.values()):return None
    points=[];faces=[]
    for i,ref in enumerate(refs):
        if not ref:continue
        y,local,triangles=tiles[ref-1];x,z=i%w,i//w;vbase=len(points)
        points.extend((x*sx+vx,y+vy,-(z*sz+vz)) for vx,vy,vz in local)
        faces.extend(tuple(vbase+j for j in face) for face in triangles)
    return end,points,faces,w,h


def regions(rom, *, check=lambda:None, **kwargs):
    result=[];pos=0
    while (pos:=rom.find(b'46d\0',pos))>=0:
        check();base=pos-0x30
        if base>=0 and base%4==0 and rom[base:base+4]==b'\0\0\0\x30':
            parsed=geometry(rom,base)
            if parsed:
                size,points,faces,w,h=parsed
                result.append(dict(offset=base,size=size,kind='3d model',media='model',layout=LAYOUT,
                    confidence='validated',label=f'Grid map {w}×{h}',vertices=len(points),triangles=len(faces),
                    preview_settings=dict(format='auto',source='rom',offset=base),
                    reason='A bounded grid and tile index resolve every vertex and triangle in this map.'))
        pos+=4
    return result


def preview(rom,asset,selection):
    parsed=geometry(rom,asset['offset'])
    if not parsed:raise formats.AssetError('The grid map changed. Rescan ROM Explorer.')
    _,vertices,faces,_,_=parsed
    edges={tuple(sorted((face[i],face[(i+1)%3]))) for face in faces for i in range(3)}
    return dict(media='model',vertices=vertices,triangles=len(faces),edges=sorted(edges),
        points=sorted({i for face in faces for i in face}),
        surfaces=[dict(indices=face,uv=[[0,0]]*3,colors=[[255,255,255,255]]*3,material=0) for face in faces],
        materials=[],details=dict(format=asset['label'],vertices=len(vertices),triangles=len(faces)),
        note='Grid geometry; map textures and placed objects are separate.',
        settings=dict(format='auto',source='rom',offset=asset['offset']))
