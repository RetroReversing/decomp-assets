"""Recognize textures in a table of relocatable files, the kind a fighting game keeps its assets in.

The table is one twelve-byte entry per file, and one more that ends it: the file's data offset from the table's
end (top bit set when the file is VPK0-packed, `vpk0.py`), the word where its internal pointer chain starts,
its packed size in words, the word where its external chain starts (0xFFFF: none) and its unpacked size in
words. The first offset is 0 and each next one starts at or after the previous file's end.

A file's pointers aren't addresses on the cartridge: each pointer word holds the next chain link (high half)
and the word it points to (low half). Internal pointers point into the file; external ones into another file
whose number follows the packed data, one halfword per link. With the chains followed, the file's display lists
name each texture's file and offset exactly, and the RDP's commands give its format and size. Sprites (libultra's
`Sprite`, 68 bytes, with its `Bitmap` strips) are found the same way: a pointer at a sprite's bitmap field (+0x34)
leads to its strips, each pointing at its texels (+8); a sprite's strips are stacked into one image, their odd
rows swapped back from the order TMEM holds them in.
"""
from __future__ import annotations

import struct

from .. import formats as asset_formats
from ..formats import AssetError
from . import display_lists, vpk0

MIN_FILES = 32
MAX_FILES = 8192
MAX_FILE = 1024 * 1024
END = 0xFFFF


def table(image, at):
    """The table's files as dicts (offset, packed, size, compressed, intern, extern), or None."""
    files, base = [], None
    for index in range(MAX_FILES + 1):
        if at + 12*index + 12 > len(image):return None
        word, intern, packed, extern, size = struct.unpack_from('>IHHHH', image, at + 12*index)
        offset = word & 0x7FFFFFFF
        if index == 0 and word & 0x7FFFFFFF:return None
        if files and offset < files[-1]['offset'] + 4*files[-1]['packed']:return None
        if not packed and not size and not intern and not extern:
            if index < MIN_FILES:return None
            base = at + 12*(index + 1)
            break
        compressed = bool(word & 0x80000000)
        if not packed or not size or (not compressed and packed != size) or 4*size > MAX_FILE:return None
        if intern != END and intern >= size or extern != END and extern >= size:return None
        files.append(dict(offset=offset, packed=packed, size=size, compressed=compressed, intern=intern, extern=extern))
    if base is None or base + files[-1]['offset'] + 4*files[-1]['packed'] > len(image):return None
    for item in files:item['offset'] += base
    return files


def find(image, check=lambda: None):
    """Where the table starts, and its files, or (None, None)."""
    for at in range(0, len(image) - 64, 4):
        if not at & 0xFFFF:check()
        # The first entry: offset 0, then a second entry whose offset is the first file's packed length.
        if image[at+1] or image[at+2] or image[at+3] or image[at] not in (0, 0x80):continue
        second = int.from_bytes(image[at+12:at+16], 'big') & 0x7FFFFFFF
        if second != 4*int.from_bytes(image[at+6:at+8], 'big'):continue
        files = table(image, at)
        if files:return at, files
    return None, None


def unpack(image, item):
    data = bytes(image[item['offset']:item['offset'] + 4*item['packed']])
    out = vpk0.unpack(data, MAX_FILE) if item['compressed'] else data
    if len(out) != 4*item['size']:raise AssetError('A file in the table unpacks to another size. Rescan the ROM.')
    return out


def links(image, files, index, data):
    """The file's pointers, each as (word, file it points into, byte offset there)."""
    item, out = files[index], []
    at, seen = item['intern'], set()
    while at != END and at not in seen and 4*at + 4 <= len(data):
        seen.add(at)
        following, words = struct.unpack_from('>HH', data, 4*at)
        out.append((at, index, 4*words));at = following
    ids = item['offset'] + 4*item['packed']
    at, seen = item['extern'], set()
    while at != END and at not in seen and 4*at + 4 <= len(data):
        seen.add(at)
        following, words = struct.unpack_from('>HH', data, 4*at)
        target = int.from_bytes(image[ids:ids+2], 'big');ids += 2
        if target < len(files):out.append((at, target, 4*words))
        at = following
    return out


def _resolved(data, pointers):
    """The file with its pointers made addresses: segment 1 points into the file itself, segment 2 at another
    file (pointer number in the upper bits, the offset there in the low twelve), with where each one goes."""
    patched, targets = bytearray(data), []
    for word, file, offset in pointers[:4095]:
        targets.append((file, offset))
        struct.pack_into('>I', patched, 4*word, 0x02000000 | (len(targets) - 1) << 12)
    return bytes(patched) + bytes(0x108), targets


SPRITE = 68
FORMATS = {(0, 2): 'rgba5551-be', (0, 3): 'rgba8888', (2, 0): 'ci4', (2, 1): 'ci8', (3, 0): 'ia4', (3, 1): 'ia8',
           (3, 2): 'ia16', (4, 0): 'i4', (4, 1): 'i8'}
BITS = {0: 4, 1: 8, 2: 16, 3: 32}
TEXEL_BITS = {fmt: BITS[siz] for (_, siz), fmt in FORMATS.items()}


def sprites(data, pointers):
    """The textures of each libultra sprite in a file: (file, strips, format, width, palette) per sprite, a strip
    being (offset, rows): its strips are stacked into one image when they share a file and a row width (each strip
    starts on eight bytes, so they are rarely back to back). Places come from `pointers`, {byte offset of a
    pointer: (file, offset)}, a palette being one such place."""
    found = []
    for at, (file, bitmaps) in pointers.items():
        start = at - 0x34
        if start < 0 or start + SPRITE > len(data):continue
        x, y, width, height = struct.unpack_from('>4h', data, start)
        scale_x, scale_y = struct.unpack_from('>2f', data, start + 8)
        count, _lists = struct.unpack_from('>2h', data, start + 40)
        strip, _real = struct.unpack_from('>2h', data, start + 44)
        fmt = FORMATS.get((data[start+48], data[start+49]))
        if x or y or scale_x != 1.0 or scale_y != 1.0 or not fmt or not 0 < width <= 2048 or not 0 < height <= 2048:continue
        if not 0 < count <= 256 or not 0 < strip <= 2048 or file != pointers.get(start + 0x34, (None,))[0]:continue
        palette = pointers.get(start + 0x20) if fmt in ('ci4', 'ci8') else None
        if fmt in ('ci4', 'ci8') and palette is None:continue
        strips = []
        for k in range(count):
            bm = bitmaps + 16*k
            place = pointers.get(bm + 8) if file is not None else None
            if bm + 16 > len(data) or place is None:break
            _w, stride, _s, _t = struct.unpack_from('>4h', data, bm)
            rows = struct.unpack_from('>h', data, bm + 12)[0]
            if not 0 < stride <= 2048 or not 0 < rows <= 2048:break
            strips.append((place, stride, rows))
        if len(strips) != count:continue
        (first_file, _), stride, _rows = strips[0]
        if all(f == first_file and w == stride for (f, _), w, _ in strips):
            found.append((first_file, [(at_, rows) for (_, at_), _, rows in strips], fmt, stride, palette))
        else:found += [(f, [(at_, rows)], fmt, w, palette) for (f, at_), w, rows in strips]
    return found


def regions(image, *, check=lambda: None, progress=lambda _: None):
    """One region per file holding textures its own or other files' display lists draw."""
    at, files = find(image, check)
    if files is None:return []
    cache, found = {}, {}

    def data(index):
        if index not in cache:
            try:cache[index] = unpack(image, files[index])
            except AssetError:cache[index] = None
        return cache[index]

    for index in range(len(files)):
        if index % 32 == 0:
            check();progress(dict(phase='Reading the relocatable file table', done=index, total=len(files)))
        own = data(index)
        if own is None:continue
        pointers = links(image, files, index, own)
        place = {4*word: (file, offset) for word, file, offset in pointers}
        for file, strips, fmt, width, palette in sprites(own, place):
            texels = data(file)
            row = (width*TEXEL_BITS[fmt] + 7)//8
            if texels is None or any(at_ + row*rows > len(texels) for at_, rows in strips):continue
            offset, height = strips[0][0], sum(rows for _, rows in strips)
            if palette is not None:
                pal = data(palette[0])
                entries = 16 if fmt == 'ci4' else 256
                if pal is None or palette[1] + 2*entries > len(pal):continue
                palette = (palette[0], palette[1], entries, 'rgba5551-be')
            found.setdefault(file, {}).setdefault((offset, fmt, width, height), dict(
                file=file, offset=offset, format=fmt, width=width, height=height, palette=palette, strips=strips))
        if display_lists.G_SETTIMG not in own[::8]:continue
        patched, targets = _resolved(own, pointers)
        slots = {4*word for word, _, _ in pointers}
        for tile in display_lists._textures(patched, dict(start=0, end=len(own))):
            # Only an image the chain points at: a segment address the file holds itself is the game's own.
            if tile['space'] != 2 or tile['at'] + 4 not in slots or tile['address'] >> 12 >= len(targets):continue
            file, offset = targets[tile['address'] >> 12];offset += tile['address'] & 0xFFF
            texels = data(file)
            if texels is None or offset + tile['bytes'] > len(texels):continue
            palette = None
            if 'palette_address' in tile:
                if tile['palette_space'] != 2 or tile['palette_address'] >> 12 >= len(targets):continue
                pfile, poffset = targets[tile['palette_address'] >> 12];poffset += tile['palette_address'] & 0xFFF
                pal = data(pfile)
                if pal is None or poffset + 2*tile['palette_entries'] > len(pal):continue
                # A palette inside the texels themselves is a load this walk misread.
                if pfile == file and poffset < offset + tile['bytes'] and offset < poffset + 2*tile['palette_entries']:continue
                palette = (pfile, poffset, tile['palette_entries'], tile['palette_format'])
            elif tile['fmt'] in ('ci4', 'ci8'):continue
            key = (offset, tile['fmt'], tile['width'], tile['height'])
            texture = dict(file=file, offset=offset, format=tile['fmt'], width=tile['width'], height=tile['height'], palette=palette)
            if tile['swapped']:texture['strips'] = [(offset, tile['height'])]
            found.setdefault(file, {}).setdefault(key, texture)
    results = []
    for file, textures in sorted(found.items()):
        items = []
        for texture in sorted(textures.values(), key=lambda t: t['offset']):
            settings = dict(format=texture['format'], width=texture['width'], height=texture['height'], offset=texture['offset'])
            items.append(dict(texture, preview_settings=settings, frames=1, palettes=1 if texture['palette'] else 0,
                              frame_offsets=[texture['offset']], palette_offsets=[texture['palette'][1]] if texture['palette'] else [],
                              palette_entries=[texture['palette'][2]] if texture['palette'] else [],
                              levels=[dict(width=texture['width'], height=texture['height'], offset=0)]))
        item = files[file]
        first = items[0]['preview_settings']
        results.append(dict(offset=item['offset'], size=4*item['packed'], kind='image', confidence='validated',
                            layout='reloc-file', table=at, file=file, textures=items,
                            label=f'File {file} · {len(items)} texture(s)',
                            **{k: v for k, v in items[0].items() if k in ('frames', 'palettes', 'frame_offsets', 'palette_offsets', 'palette_entries', 'levels')},
                            preview_settings={**first, 'source': 'rom', 'offset': item['offset']},
                            reason='The file table checks out entry by entry; following each file\'s pointer chains, a display '
                                   'list loads and draws these textures from this file. Runtime use is not established.'))
    return results


def _sprite(data, item):
    """A sprite's strips stacked into one image. The game loads each strip into TMEM as a block with no row step,
    so it stores them as TMEM holds them: each strip's odd rows have their words swapped in pairs (32-bit words,
    or 64-bit for RGBA32), and they are swapped back."""
    row = (item['width']*TEXEL_BITS[item['format']] + 7)//8
    word = 8 if item['format'] == 'rgba8888' else 4
    out = bytearray()
    for at, rows in item['strips']:
        strip = bytearray(data[at:at+row*rows])
        for y in range(1, rows, 2):
            for k in range(y*row, y*row + row - 2*word + 1, 2*word):
                strip[k:k+2*word] = strip[k+word:k+2*word] + strip[k:k+word]
        out += strip
    return bytes(out)


def preview(image, asset, selection):
    """Unpack the file (and the one holding the palette) and show the chosen texture."""
    files = table(image, asset['table'])
    if not files or asset['file'] >= len(files) or files[asset['file']]['offset'] != asset['offset']:
        raise AssetError('The file table changed. Rescan the ROM.')
    texture = asset_formats.integer(selection.get('texture', 0), 'Texture', 0, len(asset['textures'])-1)
    asset_formats.integer(selection.get('frame', 0), 'Frame', 0, 0)
    asset_formats.integer(selection.get('mip', 0), 'Mip level', 0, 0)
    item = asset['textures'][texture]
    data = whole = unpack(image, files[asset['file']])
    settings = dict(item['preview_settings'])
    if item.get('strips'):
        data = _sprite(data, item)
        settings['offset'] = 0
    if item['palette']:
        pfile, poffset, _entries, palette_format = item['palette']
        palette = whole if pfile == asset['file'] else unpack(image, files[pfile])
        settings.update(palette_offset=len(data) + poffset, palette_format=palette_format)
        data = data + palette
    result = asset_formats.preview(data, settings)
    result['details'].update(texture=texture, frame=0, palette=0 if item['palette'] else 'none', note=asset['reason'])
    result['decoded'] = dict(codec='VPK0' if files[asset['file']]['compressed'] else 'stored', bytes=4*files[asset['file']]['size'],
                             block_offset=asset['offset'], member=f"file {asset['file']}")
    result['settings'] = dict(source='rom', format='auto', offset=asset['offset'], texture=texture, frame=0, palette=0, mip=0)
    return result
