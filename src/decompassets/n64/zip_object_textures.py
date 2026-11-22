"""Indexed textures referenced by archived object records and a ROM resource registry."""

import re
import struct

from .. import archives, formats
from . import zip_object_models

LAYOUT = 'zip-object-textures'
_LOADER = re.compile(rb'\x3c\x05\0\0\x24\xa5\0\0\x3c\x03(..)\x24\x63(..)'
                     rb'\x8c\x47\0\x04\x8c\x46\0\x18\0\xa3\x28\x23....\0\xe5\x28\x23', re.S)
_ROW = re.compile(rb'(?=.{8}\0{4}\x80...\x80...\0{12})', re.S)
_RECORD = struct.Struct('>16I')


def _registry(image, check):
    bases = {(int.from_bytes(m[1],'big') << 16) + int.from_bytes(m[2],'big',signed=True)
             for m in _LOADER.finditer(image)}
    bases = {v for v in bases if 0 < v < len(image)}
    if len(bases) != 1:
        return None
    base = bases.pop()
    rows, ambiguous = {}, set()
    for match in _ROW.finditer(image):
        at = match.start()
        if at % 4 or at + 64 > len(image):
            continue
        if at % 0x10000 == 0:
            check()
        ident, offset, _, load, unload, _, _, _ = struct.unpack_from('>8I',image,at)
        next_id, next_offset, zero, next_load, next_unload, x, y, z = struct.unpack_from('>8I',image,at+32)
        size = next_offset-offset
        if (next_id != ident+1 or zero or (load,unload) != (next_load,next_unload) or x or y or z
                or not 0 < size <= archives.MAX_MEMBER or base+offset+size > len(image)):
            continue
        value = base+offset,size
        if ident in rows and rows[ident] != value:
            ambiguous.add(ident)
        rows[ident] = value
    return {ident:value for ident,value in rows.items() if ident not in ambiguous}


def regions(image, *, check=lambda: None, progress=lambda _: None):
    registry = _registry(image,check)
    if not registry:
        return []
    result = []
    for member in archives.zip_members(image,check=check):
        if not member['name'].lower().endswith('.o'):
            continue
        try:
            data = archives.member_bytes(image,member)
        except formats.AssetError:
            continue
        for name,(at,size) in zip_object_models._symbols(data).items():
            if not name.endswith(b'_Textures') or not size or size % _RECORD.size:
                continue
            textures = []
            for pos in range(at,at+size,_RECORD.size):
                row = _RECORD.unpack_from(data,pos)
                ident,kind,fmt,w,h = row[:5]
                palette,pkind,pfmt = row[9:12]
                if (kind,fmt,pkind,pfmt) != (2,1,2,2) or not 1 <= w <= 2048 or not 1 <= h <= 2048:
                    continue
                pixels,colors = registry.get(ident),registry.get(palette)
                if not pixels or not colors or pixels[1] < w*h or colors[1] < 512:
                    continue
                textures.append(dict(label=f'Texture {len(textures)+1}', offset=pixels[0], palette_offset=colors[0],
                                     width=w,height=h,frames=1,palettes=1,
                                     levels=[dict(width=w,height=h,offset=0)],
                                     preview_settings=dict(format='ci8',width=w,height=h,offset=pixels[0])))
            if not textures:
                continue
            first = textures[0]
            result.append(dict(offset=member['offset'],size=member['size'],kind='image',media='image',layout=LAYOUT,
                               label=member['name']+' textures',confidence='validated',textures=textures,
                               texture_count=len(textures),frames=1,palettes=1,
                               reason='Object records and the code-backed resource registry agree on image and palette extents.',
                               preview_settings=dict(source='rom',format='auto',offset=member['offset'],
                                                     width=first['width'],height=first['height'])))
    return result


def preview(image, asset, selection):
    index = formats.integer(selection.get('texture',0),'Texture',0,len(asset['textures'])-1)
    texture = asset['textures'][index]
    at,pal,w,h = texture['offset'],texture['palette_offset'],texture['width'],texture['height']
    if not 0 <= at <= len(image)-w*h or not 0 <= pal <= len(image)-512:
        raise formats.AssetError('The texture resource changed. Rescan ROM Explorer.')
    colors = formats._rgba(image[pal:pal+512],'rgba5551-be',256)
    pixels = b''.join(colors[4*i:4*i+4] for i in image[at:at+w*h])
    result = formats.preview(pixels,dict(format='rgba8888',width=w,height=h,offset=0))
    result['details'].update(format='CI8',texture=index,note='Stored palette preview.')
    result['settings'] = dict(source='rom',format='auto',offset=asset['offset'],texture=index)
    return result
