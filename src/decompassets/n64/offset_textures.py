"""Textures in paired data and offset sections of a size-prefixed cartridge directory."""

import re
import struct
import zlib

from .. import formats

LAYOUT = 'offset-directory-textures'
KINDS = {0: 'rgba8888', 1: 'rgba5551-be', 2: 'i8', 3: 'i4', 4: 'ia16', 5: 'ia8', 6: 'ia4'}


def catalogs(image, check=lambda: None):
    # The outer directory contains a count and monotone relative section starts.
    # Its second word is zero; require two complete texture offset tables below.
    for hit in re.finditer(rb'\x00\x00\x00[\x10-\x80]\x00\x00\x00\x00', image):
        check()
        at = hit.start()
        if at % 16:
            continue
        count = image[at+3]
        size = (4 * (count+1) + 15) & ~15
        if at + size > len(image):
            continue
        offsets = struct.unpack_from(f'>{count}I', image, at+4)
        base = at+size
        if any(x % 16 or x > len(image)-base for x in offsets) or any(a > b for a, b in zip(offsets, offsets[1:])):
            continue
        pairs = []
        for index in (2, 4):
            if index+2 >= count:
                break
            start, end, table_end = (base+offsets[i] for i in (index, index+1, index+2))
            if end <= start or table_end <= end or table_end-end > 0x10000:
                break
            values = []
            for pos in range(end, table_end-3, 4):
                value = int.from_bytes(image[pos:pos+4], 'big')
                if value == 0xffffffff:
                    break
                if value > end-start or value % 16 or values and value < values[-1]:
                    break
                values.append(value)
            else:
                break
            if len(values) < 17 or values[0] != 0 or values[-1] != end-start:
                break
            # Every proposed slot begins with a bounded texture header.
            if any(not _header(image[start+a:start+b]) for a,b in zip(values, values[1:]) if a != b):
                break
            pairs.append((start, end, values))
        if len(pairs) == 2:
            yield base, offsets, pairs


def sections(image, check=lambda: None):
    for _, _, pairs in catalogs(image, check):
        yield pairs


def _header(data):
    if len(data) < 32:
        return False
    width, height, kind = data[:3]
    return (width > 0 and height > 0 and (kind & 15) <= 8 and data[5] == 1
            and 1 <= data[18] <= 128 and data[29] in (0, 1))


def unpack(data):
    if not _header(data):
        return None
    if not data[29]:
        return data
    if len(data) < 38:
        return None
    size = int.from_bytes(data[32:36], 'little')
    if not 0 < size <= formats.MAX_BYTES:
        return None
    try:
        decoder = zlib.decompressobj(-15)
        result = decoder.decompress(data[37:], size+1)
    except zlib.error:
        return None
    if len(result) != size or not decoder.eof or len(decoder.unused_data) >= 16:
        return None
    return result


def frames(data):
    if not _header(data):
        return []
    out, cursor = [], 0
    for index in range(data[18]):
        header = data[cursor:cursor+32]
        if not _header(header) or (header[2] & 15) not in KINDS:
            return []
        width, height = header[:2]
        fmt = KINDS[header[2] & 15]
        pixel_bytes = (width * formats._bits(fmt) + 7) // 8 * height
        size = int.from_bytes(header[22:24], 'big')
        if cursor+32+pixel_bytes > len(data):
            return []
        if index+1 < data[18] and (size < 32+pixel_bytes or cursor+size > len(data)):
            return []
        out.append(dict(offset=cursor+32, width=width, height=height, format=fmt,
                        swapped=bool(int.from_bytes(header[6:8], 'big') & 0x400)))
        cursor += size
    return out


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for pair in sections(image, check):
        for number, (start, end, offsets) in enumerate(pair):
            items = []
            for index, (a, b) in enumerate(zip(offsets, offsets[1:])):
                if not index % 64:
                    check()
                    progress(dict(phase='Checking cartridge texture records', done=index, total=len(offsets)-1))
                data = unpack(image[start+a:start+b])
                entries = frames(data) if data else []
                if not entries:
                    continue
                first = entries[0]
                items.append(dict(label=f'Texture {index}', offset=start+a, size=b-a,
                                  frames=len(entries), palettes=0,
                                  levels=[dict(width=first['width'], height=first['height'], offset=0)],
                                  preview_settings=dict(format=first['format'], width=first['width'],
                                                        height=first['height'], offset=first['offset'])))
            if items:
                result.append(dict(offset=start, size=end-start, kind='image', layout=LAYOUT,
                                   confidence='validated', label=f'Texture directory {number+1}', flip_vertical=number == 0,
                                   textures=items, texture_count=len(items), frames=items[0]['frames'],
                                   palettes=0, levels=items[0]['levels'],
                                   preview_settings=dict(source='rom', format='auto', offset=start),
                                   reason='A checked offset table identifies size-prefixed texture records.'))
    return result


def preview(image, asset, selection):
    index = formats.integer(selection.get('texture', 0), 'Texture', 0, len(asset['textures'])-1)
    item = asset['textures'][index]
    start, end = item['offset'], item['offset']+item['size']
    if not 0 <= start < end <= len(image):
        raise formats.AssetError('The texture directory changed. Scan ROM Explorer again.')
    data = unpack(image[start:end])
    entries = frames(data) if data else []
    if len(entries) != item['frames']:
        raise formats.AssetError('The texture record changed. Scan ROM Explorer again.')
    frame = formats.integer(selection.get('frame', 0), 'Frame', 0, len(entries)-1)
    selected = entries[frame]
    settings = {key: selected[key] for key in ('offset', 'width', 'height', 'format')}
    if selected['swapped']:
        data = bytearray(data)
        bits = formats._bits(selected['format'])
        row = (selected['width']*bits+7)//8
        half = 8 if bits == 32 else 4
        for y in range(1, selected['height'], 2):
            for pos in range(selected['offset']+y*row, selected['offset']+(y+1)*row-2*half+1, 2*half):
                data[pos:pos+2*half] = data[pos+half:pos+2*half] + data[pos:pos+half]
    if asset.get('flip_vertical'):
        data = bytearray(data)
        row = (selected['width'] * formats._bits(selected['format']) + 7) // 8
        pos = selected['offset']
        pixels = bytes(data[pos:pos+row*selected['height']])
        for y in range(selected['height']):
            data[pos+y*row:pos+(y+1)*row] = pixels[(selected['height']-y-1)*row:(selected['height']-y)*row]
    result = formats.preview(data, settings)
    result['settings'] = dict(asset['preview_settings'], texture=index, frame=frame, palette=0, mip=0)
    result['details'].update(texture=index, frame=frame, note=asset['reason'])
    return result
