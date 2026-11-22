"""Bounded world meshes from a legacy level's spatial-tree display lists."""
import struct

from .. import formats
from . import display_meshes, legacy_level_world

LAYOUT = 'legacy-level-world-meshes'
_BASE = 0x8024b000
_GROUP = 64
_MAX_LEAVES = 4096


def meshes(data, check=lambda: None):
    image=bytearray(data)
    def word(at):return struct.unpack_from('>I',image,at)[0]
    if len(image)<0x100:return []
    scene=word(0)-_BASE
    if not 0<=scene<=len(image)-0x40:return []
    root,vertex=word(scene)-_BASE,word(scene+0x24)-_BASE
    count=word(scene+0x18)
    material,pool=word(scene+0x38)-_BASE,word(scene+0x3c)-_BASE
    if not (1<=count<=100000 and 0<=vertex<=len(image)-count*16 and 0<=root<=len(image)-24
            and 0<=material<pool<len(image)):
        return []
    pending,visited,rows=[root],set(),[]
    while pending and len(visited)<2*_MAX_LEAVES and len(rows)<_MAX_LEAVES:
        check()
        at=pending.pop()
        if at in visited or not 0<=at<=len(data)-24 or at%4:continue
        visited.add(at)
        kind=struct.unpack_from('>H',image,at+8)[0]
        if kind==1:
            pending.extend((word(at+16)-_BASE,word(at+20)-_BASE))
            continue
        if kind!=2:continue
        cursor,parts,closed=at+16,[],False
        for _ in range(512):
            if cursor+8>len(data):break
            flags,size=struct.unpack_from('>HH',image,cursor)
            if not size:
                closed=not flags
                break
            start,end=cursor+8,cursor+8+size
            if size%8 or size>0x4000 or end>len(data) or image[end-8:end]!=b'\xb8\0\0\0\0\0\0\0':break
            parts.append(bytes(image[start:end-8]))
            cursor=end
        if not closed or not parts:continue
        padding=(-len(image))%8
        image.extend(bytes(padding))
        start=len(image)
        image.extend(b''.join(parts)+b'\xb8\0\0\0\0\0\0\0')
        def state(w0,w1):
            return w0==0x06000000 and w1>>24==2 and (w1&0xffffff)<pool-material
        parsed=display_meshes.geometry(image,start,len(image),{1:vertex},vertex_end=vertex+count*16,extra_state=state)
        del image[len(data):]
        if parsed:
            _,vertices,faces=parsed
            rows.append(dict(offset=at,vertices=vertices,faces=faces))
    return rows


def regions(image, *, check=lambda: None, **kwargs):
    result=[]
    for row in legacy_level_world.records(image):
        check()
        try:data=legacy_level_world.unpack(image,row)
        except formats.AssetError:continue
        found=meshes(data,check)
        if not found:continue
        listed=[dict(label=f'World sections {i+1}–{min(i+_GROUP,len(found))}',
                     vertices=sum(len(x['vertices']) for x in found[i:i+_GROUP]),
                     triangles=sum(len(x['faces']) for x in found[i:i+_GROUP]),offset=found[i]['offset'])
                for i in range(0,len(found),_GROUP)]
        result.append(dict(offset=row['start'],size=row['end']-row['start'],kind='3d model',media='model',layout=LAYOUT,
                           confidence='validated',label=row['name']+' world sections',meshes=listed,nodes=len(listed),
                           triangles=sum(x['triangles'] for x in listed),
                           reason='Bounded tree chunks share vertex state and resolve their triangle indices.',
                           preview_settings=dict(format='auto',source='rom',offset=row['start'],mesh=0)))
    return result


def preview(image,asset,selection):
    data=legacy_level_world.unpack(image,dict(start=asset['offset'],end=asset['offset']+asset['size']))
    found=meshes(data)
    if not found:raise formats.AssetError('The level model bank changed. Rescan ROM Explorer.')
    count=(len(found)+_GROUP-1)//_GROUP
    index=formats.integer(selection.get('mesh',0),'Mesh',0,count-1)
    vertices,faces=[],[]
    for section in found[index*_GROUP:(index+1)*_GROUP]:
        first=len(vertices)
        vertices.extend((x,z,-y) for x,y,z in section['vertices'])
        faces.extend(tuple(first+i for i in face) for face in section['faces'])
    edges={tuple(sorted((face[i],face[(i+1)%3]))) for face in faces for i in range(3)}
    return dict(media='model',vertices=vertices,triangles=len(faces),edges=sorted(edges),
                points=sorted({i for face in faces for i in face}),
                surfaces=[dict(indices=face,uv=[[0,0]]*3,colors=[[255,255,255,255]]*3,material=0) for face in faces],
                materials=[],details=dict(format='F3DEX world sections',vertices=len(vertices),triangles=len(faces)),
                note='A group of world sections; textures and render state are separate.',
                settings=dict(asset['preview_settings'],mesh=index))
