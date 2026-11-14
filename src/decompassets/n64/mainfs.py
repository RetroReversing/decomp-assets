"""Recognize images in the main filesystem a party-game series keeps its assets in.

The filesystem is a directory count and one offset per directory (from the filesystem's start); a directory is a
file count and one offset per file (from the directory's start); a file is its unpacked size, its packing type and
its data. Packing types (formats documented by the public-domain PartyPlanner64 project):

  0 stored; 1 LZSS with a 1 KB window filled from 0x3BE, eight flag bits a byte read low first; 2-4 a Yaz0-like
  coding with 32 flag bits a word; 5 run lengths.

Two kinds of file hold images:

- an image pack: offsets to its entries, images and palette, an image count, the bits per texel at 0x19, then
  per image its offset, width and height; 4 or 8 bits are palette indices when a palette ends the file (16-bit
  colours), else intensities; 16 and 32 bits are RGBA;
- a model, an IFF-style FORM: its BMP1 chunks are images (indexed with a PAL1 palette by number, RGBA 16 or 32,
  RGB 24, or intensity-alpha 8), its PAL1 chunks the palettes.

Only a file's first bytes are unpacked to tell its kind; images are read from the whole file when shown.
"""
from __future__ import annotations

import struct

from .. import formats as asset_formats
from ..formats import AssetError

MAX_DIRECTORIES = 512
MAX_FILES = 8192
MAX_FILE = 4 * 1024 * 1024
TYPES = (0, 1, 2, 3, 4, 5)
PEEK = 32


def _lz(src, size):
    window, at, out, i, flags = bytearray(1024), 0x3BE, bytearray(), 0, 0
    while len(out) < size:
        if not flags & 0x100:
            if i >= len(src):break
            flags = src[i] | 0xFF00;i += 1
        if flags & 1:
            if i >= len(src):break
            value = src[i];i += 1
            out.append(value);window[at] = value;at = (at + 1) & 1023
        else:
            if i + 1 >= len(src):break
            first, second = src[i], src[i+1];i += 2
            offset = ((second & 0xC0) << 2) | first
            for k in range((second & 0x3F) + 3):
                value = window[(offset + k) & 1023]
                out.append(value);window[at] = value;at = (at + 1) & 1023
        flags >>= 1
    return bytes(out[:size])


def _slide(src, size):
    out, i, word, bits = bytearray(), 0, 0, 0
    while len(out) < size:
        if not bits:
            if i + 4 > len(src):break
            word = int.from_bytes(src[i:i+4], 'big');bits = 32;i += 4
        if word & 0x80000000:
            if i >= len(src):break
            out.append(src[i]);i += 1
        else:
            if i + 1 >= len(src):break
            first, second = src[i], src[i+1];i += 2
            back, count = ((first & 0x0F) << 8 | second) + 1, (first >> 4) + 2
            if count == 2:
                if i >= len(src):break
                count = src[i] + 0x12;i += 1
            for _ in range(min(count, size - len(out))):
                out.append(out[-back] if back <= len(out) else 0)
        word = (word << 1) & 0xFFFFFFFF;bits -= 1
    return bytes(out[:size])


def _runs(src, size):
    out, i = bytearray(), 0
    while len(out) < size and i < len(src):
        code = src[i];i += 1
        if code & 0x80:
            out += src[i:i + (code & 0x7F)];i += code & 0x7F
        elif i < len(src):
            out += bytes([src[i]]) * code;i += 1
    return bytes(out[:size])


def unpack(image, at, limit=None):
    """A file's data (its first `limit` bytes, or all of it), from the file's header at `at`."""
    size, kind = struct.unpack_from('>II', image, at)
    want = min(size, limit) if limit else size
    if kind not in TYPES or size > MAX_FILE:raise AssetError('This filesystem file is not valid here. Rescan the ROM.')
    # Packed data never takes more than nine bytes for eight (type 1) or a little more for the others.
    src = bytes(image[at+8:at+8 + (want if kind == 0 else 2*want + 64)])
    data = src[:want] if kind == 0 else _lz(src, want) if kind == 1 else _runs(src, want) if kind == 5 else _slide(src, want)
    if len(data) != want:raise AssetError('This filesystem file unpacks short. Rescan the ROM.')
    return data


def files(image, root):
    """Each file as (directory, index, header offset), or None when no filesystem starts at `root`."""
    if root + 8 > len(image):return None
    count = int.from_bytes(image[root:root+4], 'big')
    if not 2 <= count <= MAX_DIRECTORIES or root + 4 + 4*count > len(image):return None
    offsets = struct.unpack_from(f'>{count}I', image, root + 4)
    if offsets[0] != 4 + 4*count or any(b <= a for a, b in zip(offsets, offsets[1:])) or root + offsets[-1] + 8 > len(image):
        return None
    out = []
    for number, offset in enumerate(offsets):
        directory = root + offset
        n = int.from_bytes(image[directory:directory+4], 'big')
        if n > MAX_FILES or directory + 4 + 4*n > len(image):return None
        if not n:continue                                                  # an empty directory
        entries = struct.unpack_from(f'>{n}I', image, directory + 4)
        if entries[0] != 4 + 4*n or any(b < a for a, b in zip(entries, entries[1:])):return None
        for index, entry in enumerate(entries):
            at = directory + entry
            if at + 8 > len(image) or int.from_bytes(image[at+4:at+8], 'big') not in TYPES:return None
            out.append((number, index, at))
        if len(out) > MAX_FILES:return None
    return out


def find(image, check=lambda: None):
    for at in range(0, len(image) - 64, 4):
        if not at & 0xFFFF:check()
        if image[at] or image[at+1] or image[at+4] or image[at+5]:continue
        count = int.from_bytes(image[at:at+4], 'big')
        if not 2 <= count <= MAX_DIRECTORIES or int.from_bytes(image[at+4:at+8], 'big') != 4 + 4*count:continue
        found = files(image, at)
        if found:return at, found
    return None, None


def _item(fmt, width, height, offset, palette=None, palette_format='rgba5551-be', entries=0):
    settings = dict(format=fmt, width=width, height=height, offset=offset)
    if palette is not None:settings.update(palette_offset=palette, palette_format=palette_format)
    return dict(preview_settings=settings, frames=1, palettes=1 if palette is not None else 0, frame_offsets=[offset],
                palette_offsets=[palette] if palette is not None else [], palette_entries=[entries] if palette is not None else [],
                levels=[dict(width=width, height=height, offset=0)])


def pack_images(data):
    """An image pack's images as preview items relative to the file, or None when the file isn't one."""
    if len(data) < 0x20:return None
    entries, _other, first, palette = struct.unpack_from('>4I', data)
    count, bits = int.from_bytes(data[16:18], 'big'), data[25]
    if entries != 0x20 or not 0 < count <= 256 or bits not in (4, 8, 16, 32) or entries + 12*count > first:return None
    if not first <= palette <= len(data):return None
    indexed = palette < len(data) and bits in (4, 8)
    if palette < len(data) and (bits not in (4, 8) or (len(data) - palette) % 2):return None
    fmt = {4: 'ci4', 8: 'ci8', 16: 'rgba5551-be', 32: 'rgba8888'}[bits] if indexed or bits > 8 else {4: 'i4', 8: 'i8'}[bits]
    items = []
    for k in range(count):
        offset, width, height = struct.unpack_from('>IHH', data, entries + 12*k)
        if not 0 < width <= 1024 or not 0 < height <= 1024 or offset < first:return None
        if offset + (width*bits + 7)//8*height > (palette if indexed else len(data)):return None
        items.append(_item(fmt, width, height, offset, palette if indexed else None,
                           entries=(len(data) - palette)//2 if indexed else 0))
    return items


def form_images(data):
    """A FORM model's BMP1 images as preview items relative to the file, or None when it has none."""
    if data[:4] != b'FORM':return None
    chunks, at = [], 8
    while at + 8 <= len(data):
        tag = data[at:at+4]
        if tag == b'HBIN':at += 4;tag = b'HBINMODE'
        length = int.from_bytes(data[at+4:at+8], 'big')
        if at + 8 + length > len(data):return None
        chunks.append((tag, at + 8, length));at += 8 + length + (length & 1)
    palettes = {}
    for tag, at, length in chunks:
        if tag == b'PAL1' and length >= 4:
            number, count = struct.unpack_from('>HH', data, at)
            if count and (length - 4) // count in (2, 4):palettes[number] = (at + 4, count, (length - 4) // count)
    items = []
    for tag, at, length in chunks:
        if tag != b'BMP1' or length < 0x11:continue
        kind, width, height = int.from_bytes(data[at+2:at+4], 'big'), *struct.unpack_from('>HH', data, at + 5)
        if not 0 < width <= 1024 or not 0 < height <= 1024:continue
        if kind in (0x128, 0x228):
            number, size = int.from_bytes(data[at+9:at+11], 'big'), int.from_bytes(data[at+0xF:at+0x11], 'big')
            if number not in palettes or size*8 not in (4*width*height, 8*width*height) or 0x11 + size > length:continue
            start, count, colour = palettes[number]
            fmt = 'ci4' if size*8 == 4*width*height else 'ci8'
            items.append(_item(fmt, width, height, at + 0x11, start, 'rgba5551-be' if colour == 2 else 'rgba8888', count))
        elif kind in (0x125, 0x126, 0x127):
            size = int.from_bytes(data[at+0xB:at+0xD], 'big')
            fmt = {0x125: 'ia8', 0x126: 'rgb888'}.get(kind) or {16: 'rgba5551-be', 32: 'rgba8888'}.get(data[at+4])
            bits = {'ia8': 8, 'rgb888': 24, 'rgba5551-be': 16, 'rgba8888': 32}.get(fmt)
            if not fmt or size != width*height*bits//8 or 0xD + size > length:continue
            items.append(_item(fmt, width, height, at + 0xD))
    return items or None


def regions(image, *, check=lambda: None, progress=lambda _: None):
    """One region per filesystem file that holds images: an image pack or a model's bitmaps."""
    root, found = find(image, check)
    if not found:return []
    results = []
    for number, (directory, index, at) in enumerate(found):
        if number % 64 == 0:
            check();progress(dict(phase='Reading the main filesystem', done=number, total=len(found)))
        try:
            head = unpack(image, at, PEEK)
            if head[:4] != b'FORM' and head[:4] != b'\0\0\0\x20':continue
            data = unpack(image, at)
        except AssetError:continue
        items = pack_images(data) if head[:4] != b'FORM' else form_images(data)
        if not items:continue
        size, kind = struct.unpack_from('>II', image, at)
        following = [a for _, _, a in found[number+1:number+2]]
        packed = (following[0] - at) if following and following[0] > at else 8 + size
        first = items[0]['preview_settings']
        results.append(dict(offset=at, size=packed, kind='image', confidence='validated', layout='mainfs',
                            root=root, directory=directory, file=index, packing=kind, textures=items,
                            label=f"File {directory}/{index} · {len(items)} {'image(s)' if head[:4] != b'FORM' else 'model texture(s)'}",
                            **{k: v for k, v in items[0].items() if k != 'preview_settings'},
                            preview_settings={**first, 'source': 'rom', 'offset': at},
                            reason='The filesystem\'s directories and file headers check out; the file unpacks to its size '
                                   'and its image headers fit it. Runtime use is not established.'))
    return results


def preview(image, asset, selection):
    """Unpack the file again and show the chosen image with its palette (a short palette is padded)."""
    found = files(image, asset['root'])
    if not found or (asset['directory'], asset['file'], asset['offset']) not in found:
        raise AssetError('The filesystem changed. Rescan the ROM.')
    texture = asset_formats.integer(selection.get('texture', 0), 'Texture', 0, len(asset['textures'])-1)
    asset_formats.integer(selection.get('frame', 0), 'Frame', 0, 0)
    asset_formats.integer(selection.get('mip', 0), 'Mip level', 0, 0)
    data = unpack(image, asset['offset']) + bytes(1024)
    result = asset_formats.preview(data, asset['textures'][texture]['preview_settings'])
    result['details'].update(texture=texture, frame=0, palette=0 if asset['textures'][texture]['palettes'] else 'none',
                             note=asset['reason'])
    result['decoded'] = dict(codec=f"filesystem packing {asset['packing']}", bytes=len(data) - 1024,
                             block_offset=asset['offset'], member=f"file {asset['directory']}/{asset['file']}")
    result['settings'] = dict(source='rom', format='auto', offset=asset['offset'], texture=texture, frame=0, palette=0, mip=0)
    return result
