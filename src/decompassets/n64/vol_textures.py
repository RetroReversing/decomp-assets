"""Indexed tiles in bounded dvoL resource archives.

The archive has a size table and either literal or LZ members. A small indexed
image resource has one palette and one tiled image; each tile is previewed in
its local coordinates. The decoder was checked against the game's runtime output.
"""
import struct

from .. import formats

LAYOUT = 'vol-indexed-tiles'
LIMIT = 4 * 1024 * 1024


def unpack(data, size):
    if not 0 < size <= LIMIT:
        raise formats.AssetError('The resource exceeds the decoding limit.')
    pos, bits, out = 0, 1, bytearray()
    while pos < len(data):
        if bits == 1:
            if pos + 2 > len(data):raise formats.AssetError('Incomplete resource flags.')
            bits = int.from_bytes(data[pos:pos+2], 'little') | 0x10000
            pos += 2
        if bits & 1:
            if pos + 2 > len(data):raise formats.AssetError('Incomplete resource match.')
            a, b = data[pos:pos+2];pos += 2
            distance, count = ((a & 0xf0) << 4) | b, (a & 15) + 3
            if not distance or distance > len(out) or len(out) + count > size:
                raise formats.AssetError('Invalid resource match.')
            for _ in range(count):out.append(out[-distance])
        else:
            if pos >= len(data) or len(out) >= size:raise formats.AssetError('Incomplete resource literal.')
            out.append(data[pos]);pos += 1
        bits >>= 1
    if len(out) != size:raise formats.AssetError('The resource size does not match its table.')
    return bytes(out)


def archive(data, at):
    if data[at:at+4] != b'dvoL' or at + 52 > len(data):return None
    count, header = struct.unpack_from('>II', data, at + 12)
    if count != 4 or header != 52:return None
    cursor, members = at + header, []
    for i in range(count):
        word, size = struct.unpack_from('>II', data, at + 20 + i*8)
        kind, length = word & 0xfff00000, word & 0xfffff
        if kind not in (0x01000000, 0x01200000) or not 0 < size <= LIMIT or not length or cursor + length > len(data):return None
        raw = data[cursor:cursor+length]
        try:member = unpack(raw, size) if kind == 0x01200000 else bytes(raw)
        except formats.AssetError:return None
        if len(member) != size:return None
        members.append(member);cursor += length
    if not members[0].startswith(b'\0\1\0\x37\0\0\0\4'):return None
    palettes = [x for x in members[1:] if len(x) == 520 and x[0] == 1]
    images = []
    for x in members[1:]:
        if len(x) < 16 or x[7] != 0x21:continue
        pitch, w, h = int.from_bytes(x[:2], 'big'), x[2], x[3]
        tiles = x[5] + 1
        if 1 <= w <= 64 and 1 <= h <= 64 and pitch == w*h and len(x) == 16 + pitch*tiles:
            images.append((x, w, h, tiles))
    if len(palettes) != 1 or len(images) != 1:return None
    return cursor-at, palettes[0], images[0]


def regions(image, *, check=lambda: None, **kwargs):
    result=[];at=0
    while (at := image.find(b'dvoL', at)) >= 0:
        check(); found=archive(image, at)
        if found:
            size, _, (_, w, h, count) = found
            items=[dict(label=f'Tile {i+1}', size=w*h, frames=1, palettes=1,
                        levels=[dict(width=w, height=h, offset=0)]) for i in range(count)]
            result.append(dict(offset=at, size=size, kind='image', media='image', layout=LAYOUT,
                               confidence='validated', label=f'Indexed image · {count} tiles',
                               textures=items, texture_count=count, frames=1, palettes=1,
                               levels=items[0]['levels'], preview_settings=dict(format='auto', source='rom', offset=at, texture=0),
                               reason='A bounded resource table identifies an indexed tile image and its palette.'))
        at += 4
    return result


def preview(image, asset, selection):
    found=archive(image, asset['offset'])
    if not found:raise formats.AssetError('The indexed resource changed. Rescan ROM Explorer.')
    _, palette, (pixels,w,h,count)=found
    index=formats.integer(selection.get('texture',0),'Texture',0,count-1)
    data=pixels[16+index*w*h:16+(index+1)*w*h] + palette[8:]
    result=formats.preview(data,dict(format='ci8',width=w,height=h,offset=0,palette_offset=w*h,palette_format='rgba5551-be'))
    result['settings']=dict(source='rom',format='auto',offset=asset['offset'],texture=index)
    result['details'].update(texture=index,note=asset['reason'])
    return result
