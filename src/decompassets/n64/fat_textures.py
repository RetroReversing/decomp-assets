"""Texture descriptors and indexed images in a structured cartridge file table."""

import base64
import re
import struct

from .. import formats

LAYOUT = 'fat-indexed-textures'


def file_tables(image, check=lambda: None):
    """Find a complete file-allocation directory and its matching data header."""
    for match in re.finditer(rb'\x00\x00\x00[\x02-\x80]\x00\x00', image):
        fat = match.start()
        if fat % 4 or fat+12 > len(image):
            continue
        levels = image[fat+3]
        table_count = levels+2
        if int.from_bytes(image[fat+4:fat+8], 'big') != 4+table_count*8:
            continue
        tables, spans = [], []
        for i in range(table_count):
            check()
            at = fat+4+i*8
            if at+8 > len(image):
                break
            off, count = struct.unpack_from('>II', image, at)
            if not 0 < count <= 20000 or off < 4+table_count*8 or fat+off+8*count > len(image):
                break
            rows = list(struct.iter_unpack('>IHH', image[fat+off:fat+off+8*count]))
            if any(k > 255 or idx >= 0x8000 for _,k,idx in rows):
                break
            if any(a[0] > b[0] for a,b in zip(rows,rows[1:])):
                break
            tables.append(rows)
            spans.append((fat+off, count*8))
        if len(tables) != table_count or sum(k == 63 for _,k,_ in tables[0]) < 16:
            continue
        # The data header has the same level count and three checked image-pointer tables.
        marker = struct.pack('>H', levels)
        for candidate in re.finditer(re.escape(marker), image[:fat]):
            base = candidate.start()-8
            if base < 0 or base%4 or base+180 > fat:
                continue
            count = int.from_bytes(image[base+4:base+6], 'big')
            if not 1 <= count <= 4096:
                continue
            pointers = []
            for i in range(3):
                off,size = struct.unpack_from('>II', image, base+156+i*8)
                if not 16 <= size <= 0x10000 or size%4 or off < 180 or base+off+size > fat:
                    break
                entries = list(struct.unpack_from(f'>{size//4}I', image, base+off))
                if (any(not 0 < x < fat-base for x in entries)
                        or any(a > b for a,b in zip(entries, entries[1:]))):
                    break
                pointers.append(entries)
            if len(pointers) != 3:
                continue
            fixed = [(off,idx) for off,kind,idx in tables[0] if kind == 63]
            if sum(_descriptor(image, base+off, pointers, base, fat) is not None for off,_ in fixed[:32]) < 24:
                continue
            yield base, fat, tables, pointers, spans


def _descriptor(image, at, pointers, base, end):
    if not base <= at <= end-12:
        return None
    tex,palette,alpha,w,h,flags,_ = struct.unpack_from('>HHHBBHH', image, at)
    if not 2 <= w <= 9 or not 2 <= h <= 9 or flags&7 not in (0,1,2,4):
        return None
    width,height = 1 << w,1 << h
    kind = flags&7
    table = {1:0, 2:1, 4:2}.get(kind)
    if tex == 0xffff:
        table = None
    if table is not None and tex >= len(pointers[table]):
        return None
    if alpha != 0xffff and alpha >= len(pointers[0]):
        return None
    if table is None and alpha == 0xffff:
        return None
    bits = (4,8,16)[table] if table is not None else 4
    source = base+pointers[table][tex] if table is not None else base+pointers[0][alpha]
    if source + width*height*bits//8 > end:
        return None
    alpha_at = base+pointers[0][alpha] if alpha != 0xffff else None
    if alpha_at is not None and alpha_at+width*height//2 > end:
        return None
    return dict(width=width,height=height,kind=table,source=source,palette=palette,alpha=alpha_at)


def _palette(tables, number, index):
    index &= 0x7fff
    for table in (tables[number], tables[1], tables[0], *tables[2:]):
        for off,kind,key in table:
            if kind == 21 and key == index:
                return off
    return None


def regions(image, *, check=lambda: None, progress=lambda _: None):
    results = []
    for base, end, tables, pointers, spans in file_tables(image,check):
        for number, table in enumerate(tables):
            check()
            items = []
            for off,kind,index in table:
                if kind != 63:
                    continue
                desc = _descriptor(image,base+off,pointers,base,end)
                if not desc:
                    continue
                palette = desc['palette']
                if palette != 0xffff:
                    palette = _palette(tables,number,palette)
                    if palette is None:
                        continue
                    palette += base
                    needed = 512 if desc['kind'] == 1 else 32
                    if palette+needed > end:
                        continue
                else:
                    palette = None
                desc['palette'] = palette
                width,height = desc['width'],desc['height']
                fmt = ('ci4' if palette is not None else 'i4') if desc['kind'] == 0 else (
                    ('ci8' if palette is not None else 'i8') if desc['kind'] == 1 else
                    ('rgba5551-be' if desc['kind'] == 2 else 'i4'))
                items.append(dict(label=f'Texture {index}', descriptor=base+off, **desc,
                                  frames=1, palettes=int(palette is not None),
                                  levels=[dict(width=width,height=height,offset=0)],
                                  preview_settings=dict(format=fmt,width=width,height=height,offset=desc['source'])))
            if not items:
                continue
            start, size = spans[number]
            results.append(dict(offset=start,size=size,kind='image',layout=LAYOUT,confidence='validated',
                                label=f'Texture table {number+1}',textures=items,texture_count=len(items),
                                frames=1,palettes=items[0]['palettes'],levels=items[0]['levels'],
                                preview_settings=dict(source='rom',format='auto',offset=start),
                                reason='The file table links texture descriptors, image offsets and palette records.'))
    return results


def preview(image, asset, selection):
    index = formats.integer(selection.get('texture',0),'Texture',0,len(asset['textures'])-1)
    item = asset['textures'][index]
    settings = dict(item['preview_settings'])
    if item['palette'] is not None:
        settings.update(palette_offset=item['palette'],palette_format='rgba5551-be')
    pixels,details = formats.texture_pixels(image,settings)
    pixels = bytearray(pixels)
    if item['kind'] is None or item['kind'] == 1 and item['palette'] is None:
        for i in range(0,len(pixels),4):
            pixels[i:i+4] = bytes((255,255,255,pixels[i]))
    if item['alpha'] is not None:
        raw = formats._take(image,item['alpha'],item['width']*item['height']//2)
        for i in range(item['width']*item['height']):
            pixels[i*4+3] = ((raw[i//2] >> (4 if i%2 == 0 else 0)) & 15)*17
    payload = formats._png(item['width'],item['height'],pixels)
    return dict(media='image',mime='image/png',data_url='data:image/png;base64,'+base64.b64encode(payload).decode(),
                details={**details,'texture':index,'note':asset['reason']},
                settings=dict(asset['preview_settings'],texture=index,frame=0,palette=0,mip=0))
