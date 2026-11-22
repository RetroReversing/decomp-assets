"""CI4 texture packs with self-relative image and palette pointers inside EDL blocks."""

import struct

from .. import formats
from . import edl

LAYOUT = 'eurocom-edl-indexed-textures'


def textures(data):
    if len(data) < 32:
        return []
    kind, size, count, palettes, desc_rel, stride, header_rel = struct.unpack_from('>IIHHIII',data)
    if (kind != 5 or size != len(data) or not 1 <= count <= 2048 or not 1 <= palettes <= count
            or stride != 16):
        return []
    desc = 12+desc_rel
    header = 20+header_rel
    if not 32 <= desc <= len(data)-count*16 or not desc+count*16 <= header <= len(data)-4-count*4:
        return []
    pal_table = header+int.from_bytes(data[header:header+4],'big')
    if not header+4+count*4 <= pal_table <= len(data)-palettes*4:
        return []
    pal_offsets = []
    for i in range(palettes):
        slot = pal_table+4*i
        offset = slot+int.from_bytes(data[slot:slot+4],'big')
        if not pal_table+palettes*4 <= offset <= len(data)-32:
            return []
        pal_offsets.append(offset)
    if any(a+32 > b for a,b in zip(pal_offsets,pal_offsets[1:])):
        return []
    result = []
    previous_end = max(pal_offsets)+32
    for i in range(count):
        units, height, _, _, palette, _ = struct.unpack_from('>HHIIHH',data,desc+16*i)
        width = units*4
        slot = header+4+4*i
        pointer = int.from_bytes(data[slot:slot+4],'big')
        offset = slot+(pointer >> 8)
        length = width*height//2
        if (not 4 <= width <= 2048 or not 1 <= height <= 2048 or width*height > formats.MAX_PIXELS
                or palette >= palettes or pointer & 255 > 2 or offset < previous_end or offset+length > len(data)):
            return []
        previous_end = offset+length
        settings = dict(format='ci4',width=width,height=height,offset=offset,
                        palette_offset=pal_offsets[palette],palette_format='rgba5551-be')
        result.append(dict(label=f'Texture {i}',preview_settings=settings,frames=1,palettes=1,
                           levels=[dict(width=width,height=height,offset=0)]))
    return result


def regions(image, blocks, check):
    result = []
    for offset, (_, stored, decoded) in blocks.items():
        if decoded > formats.MAX_BYTES:
            continue
        check()
        try:
            data = edl.unpack(image,offset)
        except formats.AssetError:
            continue
        items = textures(data)
        if items:
            result.append(dict(offset=offset,size=stored,kind='image',media='image',layout=LAYOUT,
                               confidence='validated',label=f'{len(items)} indexed textures',
                               textures=items,texture_count=len(items),frames=1,palettes=1,levels=items[0]['levels'],
                               preview_settings=dict(source='rom',format='auto',offset=offset),
                               reason='The decompressed pack links bounded image and palette records.'))
    return result


def preview(image, asset, selection):
    slot = formats.integer(selection.get('texture',0),'Texture',0,len(asset['textures'])-1)
    data = edl.unpack(image,asset['offset'])
    items = textures(data)
    if slot >= len(items) or items[slot] != asset['textures'][slot]:
        raise formats.AssetError('The texture pack changed. Scan ROM Explorer again.')
    result = formats.preview(data,items[slot]['preview_settings'])
    result['settings'] = dict(source='rom',format='auto',offset=asset['offset'],texture=slot,frame=0,palette=0,mip=0)
    result['details'].update(texture=slot,note=asset['reason'])
    return result
