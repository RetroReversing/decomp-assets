"""Rigid meshes from a validated directory of compressed relocatable resources."""
import re
import struct
import zlib

from .. import formats

LAYOUT = 'reloc-level-object-meshes'
IMAGE = 'reloc-level-object-textures'
_NAME = re.compile(rb'[a-z0-9_]{8}')


def members(image):
    """An ordered directory bounds adjacent raw DEFLATE members."""
    for match in _NAME.finditer(image[:min(len(image), 0x200000)]):
        at = match.start()
        if at % 4:
            continue
        rows = []
        for pos in range(at, min(at+2048*16, len(image)-15), 16):
            name = image[pos:pos+8]
            if not _NAME.fullmatch(name):
                break
            lo, hi = struct.unpack_from('>II', image, pos+8)
            if (not 0x1000 <= lo < hi <= len(image) or (lo | hi) % 16
                    or rows and rows[-1]['end'] != lo or any(item['name'] == name for item in rows)):
                break
            rows.append(dict(name=name, start=lo, end=hi))
        if len(rows) >= 16:
            return rows
    return []


def unpack(image, row):
    try:
        stream = zlib.decompressobj(-15)
        data = stream.decompress(image[row['start']:row['end']], formats.MAX_BYTES+1)
    except zlib.error as error:
        raise formats.AssetError('The object stream is damaged.') from error
    if not stream.eof or len(data) > formats.MAX_BYTES:
        raise formats.AssetError('The object stream is incomplete or too large to preview.')
    return data


def meshes(data):
    if len(data) < 8:
        return []
    count = struct.unpack_from('>I', data)[0]
    base = 4+4*count
    if not 1 <= count <= 65536 or base+0x30 > len(data):
        return []
    offsets = struct.unpack_from(f'>{count}I', data, 4)
    relocs = set(offsets)
    if len(relocs) != count or any(offset % 4 or base+offset+4 > len(data) for offset in offsets):
        return []
    def u32(offset):
        return struct.unpack_from('>I', data, base+offset)[0]
    n = struct.unpack_from('>H', data, base+8)[0]
    if not 1 <= n <= 64 or 0xc not in relocs:
        return []
    table = u32(0xc)
    if table % 4 or base+table+4*n > len(data):
        return []
    result = []
    for i in range(n):
        if table+4*i not in relocs:
            continue
        at = u32(table+4*i)
        if at % 4 or base+at+0x38 > len(data) or at+8 not in relocs or at+0x14 not in relocs:
            continue
        nv, nf, segments = struct.unpack_from('>H2xHH', data, base+at)
        if not 3 <= nv <= 16384 or not 1 <= nf <= 32768 or segments != 1:
            continue
        vertex, face = u32(at+8), u32(at+0x14)
        if (vertex % 2 or face % 2 or base+vertex+8*nv > len(data) or base+face+12*nf > len(data)):
            continue
        points = [struct.unpack_from('>3h', data, base+vertex+8*j) for j in range(nv)]
        triangles = [struct.unpack_from('>3H', data, base+face+12*j) for j in range(nf)]
        if any(max(triangle) >= nv or len(set(triangle)) < 3 for triangle in triangles):
            continue
        result.append(dict(offset=at, vertices=points, faces=triangles))
    return result



def textures(data, found):
    count = struct.unpack_from('>I', data)[0]
    base = 4+4*count
    relocs = set(struct.unpack_from(f'>{count}I', data, 4))
    pools = {base+struct.unpack_from('>I', data, base+x['offset']+0x34)[0]
             for x in found if x['offset']+0x34 in relocs
             and struct.unpack_from('>I', data, base+x['offset']+0x34)[0]}
    if len(pools) != 1:
        return []
    result, seen = [], set()
    for match in re.finditer(b'\xe7\x00\x00\x00\x00\x00\x00\x00', data):
        at = match.start()
        if at+0x68 > len(data):
            continue
        commands = [struct.unpack_from('>II', data, at+8*j) for j in range(13)]
        if ([x[0] >> 24 for x in commands] != [0xe7,0xe3,0xfd,0xf5,0xf0,0xf5,0xe6,0xfd,0xf3,0xf5,0xf2,0xe6,0xdf]
                or commands[2][0] != 0xfd100000 or commands[7][0] != 0xfd500000
                or commands[2][1] >> 24 != 5 or commands[7][1] >> 24 != 5
                or commands[10][0] != 0xf2000000 or commands[10][1] & 0x003003):
            continue
        tile = commands[10][1]
        width, height = ((tile >> 12) & 0xfff)//4+1, (tile & 0xfff)//4+1
        size = (width*height+1)//2
        if not 1 <= width <= 256 or not 1 <= height <= 256:
            continue
        for pool in pools:
            palette = pool+(commands[2][1] & 0xffffff)
            pixels = pool+(commands[7][1] & 0xffffff)
            key = (palette,pixels,width,height)
            if (key in seen or not 0 <= palette <= len(data)-32 or not 0 <= pixels <= len(data)-size
                    or not any(data[palette:palette+32])):
                continue
            seen.add(key)
            result.append(dict(offset=pixels, format='ci4', width=width, height=height,
                               palette_offset=palette, palette_format='rgba5551-be'))
    return result

def regions(image, *, check=lambda: None, **kwargs):
    result = []
    for row in members(image):
        check()
        try:
            found = meshes(unpack(image,row))
        except formats.AssetError:
            continue
        if not found:
            continue
        items = textures(unpack(image, row), found)
        if items:
            images = [dict(label=f'Texture {i+1}', width=x['width'], height=x['height'], frames=1, palettes=1,
                           palette_entries=[16], levels=[dict(width=x['width'], height=x['height'], offset=0)],
                           preview_settings=x) for i,x in enumerate(items)]
            result.append(dict(offset=row['start'], size=row['end']-row['start'], kind='image', media='image',
                               layout=IMAGE, confidence='validated', label=row['name'].decode('ascii').rstrip('_')+' textures',
                               textures=images, texture_count=len(images), frames=1,
                               reason='Rigid object texture pools and material display lists bound the CI4 pixels and palette.',
                               preview_settings=dict(format='auto', source='rom', offset=row['start'], texture=0)))
        listed = [dict(label=f'Mesh {i+1}', vertices=len(x['vertices']), triangles=len(x['faces']), offset=x['offset'])
                  for i,x in enumerate(found)]
        result.append(dict(offset=row['start'], size=row['end']-row['start'], kind='3d model', media='model',
                           layout=LAYOUT, confidence='validated', label=row['name'].decode('ascii').rstrip('_')+' object',
                           meshes=listed, nodes=len(listed), triangles=sum(x['triangles'] for x in listed),
                           reason='Relocation entries, rigid mesh records, vertices and face indices are bounded.',
                           preview_settings=dict(format='auto', source='rom', offset=row['start'], mesh=0)))
    return result


def preview(image, asset, selection):
    row = dict(start=asset['offset'], end=asset['offset']+asset['size'])
    found = meshes(unpack(image, row))
    if not found:
        raise formats.AssetError('The object model changed. Rescan ROM Explorer.')
    if asset['layout'] == IMAGE:
        items = textures(unpack(image, row), found)
        if not items:
            raise formats.AssetError('The object texture bank changed. Rescan ROM Explorer.')
        index = formats.integer(selection.get('texture', 0), 'Texture', 0, len(items)-1)
        result = formats.preview(unpack(image, row), items[index])
        result['settings'] = dict(asset['preview_settings'], texture=index)
        result['details']['note'] = asset['reason']
        return result
    index = formats.integer(selection.get('mesh', 0), 'Mesh', 0, len(found)-1)
    vertices = [(x,z,-y) for x,y,z in found[index]['vertices']]
    faces = found[index]['faces']
    edges = {tuple(sorted((face[i],face[(i+1)%3]))) for face in faces for i in range(3)}
    return dict(media='model', vertices=vertices, triangles=len(faces), edges=sorted(edges),
                points=sorted({i for face in faces for i in face}),
                surfaces=[dict(indices=face, uv=[[0,0]]*3, colors=[[255,255,255,255]]*3, material=0) for face in faces],
                materials=[], details=dict(format='Rigid object mesh', vertices=len(vertices), triangles=len(faces)),
                note='Local rigid geometry; textures and placement are separate.',
                settings=dict(asset['preview_settings'], mesh=index))
