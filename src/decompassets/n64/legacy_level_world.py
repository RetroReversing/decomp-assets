"""Validated compressed level records in an indexed shared-overlay directory."""
import struct
import zlib

from .. import formats


def records(image):
    if len(image) < 0x2000:
        return []
    for at in range(0x1000, min(len(image)-160, 0x200000), 4):
        lo,hi,code,end,ram = struct.unpack_from('>5I',image,at)
        if not (0x1000 <= code < end < lo < hi <= len(image) and 0x80000400 <= ram <= 0x80800000
                and not (lo | hi | code | end) % 16):
            continue
        rows=[]
        for pos in range(at, min(at+64*32,len(image)-31),32):
            lo,hi,code,end,ram=struct.unpack_from('>5I',image,pos)
            if not (0x1000 <= code < end < lo < hi <= len(image) and 0x80000400 <= ram <= 0x80800000
                    and not (lo | hi | code | end) % 16):
                break
            rows.append(dict(name=f'Level {len(rows)+1}',start=lo,end=hi))
        if len(rows) < 8:
            continue
        try:
            for row in (rows[0],rows[-1]):
                stream=zlib.decompressobj(-15)
                data=stream.decompress(image[row['start']:row['end']],formats.MAX_BYTES+1)
                if not stream.eof or len(data) > formats.MAX_BYTES or len(data)<0x100:
                    raise ValueError
        except (zlib.error,ValueError):
            continue
        return rows
    return []


IMAGE = 'legacy-level-world-textures'
_BASE = 0x8024b000


def textures(data):
    if len(data) < 0x100:
        return []
    def word(at):
        return struct.unpack_from('>I',data,at)[0]
    scene = word(0)-_BASE
    if not 0 <= scene <= len(data)-0x40:
        return []
    material, pool = word(scene+0x38)-_BASE, word(scene+0x3c)-_BASE
    if not 0 <= material < pool < len(data) or material % 8:
        return []
    result, seen = [], set()
    for at in range(material,pool-0x67,8):
        commands = [struct.unpack_from('>II',data,at+8*j) for j in range(13)]
        if ([x[0] >> 24 for x in commands] != [0xe7,0xba,0xfd,0xf5,0xf0,0xf5,0xe6,0xfd,0xf3,0xf5,0xf2,0xe6,0xb8]
                or commands[2][0] != 0xfd100000 or commands[7][0] != 0xfd500000
                or commands[2][1] >> 24 != 3 or commands[7][1] >> 24 != 3
                or commands[10][0] != 0xf2000000 or commands[10][1] & 0x003003):
            continue
        palette = pool+(commands[2][1]&0xffffff)
        pixels = pool+(commands[7][1]&0xffffff)
        tile = commands[10][1]
        width,height = ((tile>>12)&0xfff)//4+1, (tile&0xfff)//4+1
        size = (width*height+1)//2
        key = (palette,pixels,width,height)
        if (key in seen or not 1 <= width <= 256 or not 1 <= height <= 256
                or not 0 <= palette <= len(data)-32 or not 0 <= pixels <= len(data)-size
                or not any(data[palette:palette+32])):
            continue
        seen.add(key)
        result.append(dict(offset=pixels,format='ci4',width=width,height=height,
                           palette_offset=palette,palette_format='rgba5551-be'))
    return result


def unpack(image,row):
    try:
        stream=zlib.decompressobj(-15)
        data=stream.decompress(image[row['start']:row['end']],formats.MAX_BYTES+1)
    except zlib.error as error:
        raise formats.AssetError('The level stream is damaged.') from error
    if not stream.eof or len(data)>formats.MAX_BYTES:
        raise formats.AssetError('The level stream is incomplete or too large to preview.')
    return data


def regions(image, *, check=lambda: None, **kwargs):
    result=[]
    for row in records(image):
        check()
        try:
            data=unpack(image,row)
        except formats.AssetError:
            continue
        found=textures(data)
        if not found:
            continue
        listed=[dict(label=f'Texture {i+1}',width=x['width'],height=x['height'],frames=1,palettes=1,
                     palette_entries=[16],levels=[dict(width=x['width'],height=x['height'],offset=0)],
                     preview_settings=x) for i,x in enumerate(found)]
        result.append(dict(offset=row['start'],size=row['end']-row['start'],kind='image',media='image',layout=IMAGE,
                           confidence='validated',label=row['name']+' textures',textures=listed,texture_count=len(listed),
                           frames=1,reason='Level pointers and material commands bound the CI4 pixels and palette.',
                           preview_settings=dict(format='auto',source='rom',offset=row['start'],texture=0)))
    return result


def preview(image,asset,selection):
    data=unpack(image,dict(start=asset['offset'],end=asset['offset']+asset['size']))
    rows=textures(data)
    if not rows:
        raise formats.AssetError('The level texture bank changed. Rescan ROM Explorer.')
    index=formats.integer(selection.get('texture',0),'Texture',0,len(rows)-1)
    result=formats.preview(data,rows[index])
    result['settings']=dict(asset['preview_settings'],texture=index)
    result['details']['note']=asset['reason']
    return result
