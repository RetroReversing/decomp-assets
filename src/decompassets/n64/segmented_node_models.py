"""Local geometry from compressed, segmented model nodes and four-triangle lists."""
import struct
import zlib

from .. import formats

LAYOUT = 'segmented-node-meshes'
MAX_OUTPUT = 1024 * 1024


def unpack(data):
    if data[:2] != b'\x11\x72':return None
    try:
        z=zlib.decompressobj(-15);decoded=z.decompress(data[2:],MAX_OUTPUT+1)
    except zlib.error:return None
    if not z.eof or len(decoded)>MAX_OUTPUT:return None
    return decoded, len(data)-len(z.unused_data)


def _ptr(value, limit):
    offset=value&0xffffff
    return offset if value>>24==5 and offset<limit else None


def geometry(data, dl, vertices, count):
    if dl%8 or vertices%4 or not 0<count<=4096 or vertices+count*16>len(data):return None
    cache=[None]*16;faces=[]
    for at in range(dl,min(len(data)-7,dl+8192),8):
        a,b=struct.unpack_from('>II',data,at);cmd=a>>24
        if cmd==0xb8:
            if a!=0xb8000000 or b or not faces:return None
            points=[struct.unpack_from('>3h',data,vertices+i*16) for i in range(count)]
            return points,faces
        if cmd==4:
            n=((a>>20)&15)+1;dest=(a>>16)&15;offset=b&0xffffff
            if (a&0xffff)!=n*16 or b>>24!=4 or offset%16 or dest+n>16 or offset+n*16>count*16:return None
            for j in range(n):cache[dest+j]=offset//16+j
        elif cmd==0xb1:
            if a&0x00ff0000:return None
            for j in range(4):
                tri=((b>>(j*8))&15,(b>>(j*8+4))&15,(a>>(j*4))&15)
                if tri==(0,0,0):continue
                if any(cache[x] is None for x in tri):return None
                faces.append(tuple(cache[x] for x in tri))
        elif cmd==0xbf:
            tri=[(b>>s)&255 for s in (16,8,0)]
            if a!=0xbf000000 or b>>24 or any(x%10 or x//10>=16 or cache[x//10] is None for x in tri):return None
            faces.append(tuple(cache[x//10] for x in tri))
        elif cmd==1 and (a&0xffff)==0x40 and b>>24==3:continue
        elif cmd in tuple(range(0xe6,0x100))+(0xb6,0xb7,0xb9,0xba,0xbb,0xbc,0xbd,0xc0):continue
        else:return None
    return None


def meshes(data,check=lambda:None):
    if len(data)<32:return []
    root=_ptr(int.from_bytes(data[:4],'big'),len(data));stack=[root];seen=set();result=[]
    while stack and len(seen)<5000:
        check();node=stack.pop()
        if node is None or node in seen or node%4 or node+24>len(data):continue
        seen.add(node);op,record,*links=struct.unpack_from('>6I',data,node);kind=(op>>16)&255
        if kind not in range(1,32):continue
        stack.extend(_ptr(value,len(data)) for value in links)
        if kind not in (4,24):continue
        rec=_ptr(record,len(data))
        if rec is None or rec+32>len(data):continue
        primary,_,third,fourth=struct.unpack_from('>4I',data,rec)
        dl=_ptr(primary,len(data));vertex=_ptr(fourth if kind==4 else third,len(data))
        count=struct.unpack_from('>H',data,rec+(16 if kind==4 else 12))[0]
        if dl is None or vertex is None:continue
        parsed=geometry(data,dl,vertex,count)
        if parsed:
            points,faces=parsed
            result.append(dict(node=node,display_list=dl,vertex_offset=vertex,vertex_count=count,
                               vertices=len(points),triangles=len(faces)))
    return result


def regions(rom, *, check=lambda:None, **kwargs):
    result=[];at=0
    while (at:=rom.find(b'\x11\x72',at))>=0:
        check();decoded=unpack(rom[at:at+0x10000])
        if decoded:
            data,used=decoded
            found=meshes(data,check) if data[:1]==b'\x05' else []
            if found:
                rows=[dict(label=f'Mesh {i+1}',**entry) for i,entry in enumerate(found)]
                result.append(dict(offset=at,size=used,compressed=True,kind='3d model',media='model',layout=LAYOUT,
                    confidence='validated',label=f'Model · {len(rows)} meshes',meshes=rows,nodes=len(rows),
                    triangles=sum(item['triangles'] for item in rows),
                    preview_settings=dict(format='auto',source='rom',offset=at,mesh=0),
                    reason='A reachable model node links bounded vertices to a closed four-triangle display list.'))
        at+=2
    return result


def preview(rom,asset,selection):
    decoded=unpack(rom[asset['offset']:asset['offset']+asset['size']])
    if not decoded:raise formats.AssetError('The compressed model changed. Rescan ROM Explorer.')
    data,_=decoded;found=meshes(data)
    if not found:raise formats.AssetError('The model nodes changed. Rescan ROM Explorer.')
    index=formats.integer(selection.get('mesh',0),'Mesh',0,len(found)-1);row=found[index]
    parsed=geometry(data,row['display_list'],row['vertex_offset'],row['vertex_count'])
    if not parsed:raise formats.AssetError('The model geometry changed. Rescan ROM Explorer.')
    vertices,faces=parsed;edges={tuple(sorted((face[i],face[(i+1)%3]))) for face in faces for i in range(3)}
    return dict(media='model',vertices=vertices,triangles=len(faces),edges=sorted(edges),
        points=sorted({i for face in faces for i in face}),
        surfaces=[dict(indices=face,uv=[[0,0]]*3,colors=[[255,255,255,255]]*3,material=0) for face in faces],
        materials=[],details=dict(format=asset['label'],vertices=len(vertices),triangles=len(faces)),
        note='Local geometry from one model node. Scene transforms and materials are separate.',
        settings=dict(format='auto',source='rom',offset=asset['offset'],mesh=index))
