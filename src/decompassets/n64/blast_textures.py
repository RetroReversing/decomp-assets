"""Recognize textures packed with a demolition game's own back-reference codecs, from its texture table.

The table is one eight-byte entry per resource (offset from the table, packed size, codec), the first resource
starting right after the table and nearly every next one at the previous one's end, rounded up to eight bytes. Codec 0 is
stored data (among it the look-up tables codecs 4 and 5 read: 256 bytes for codec 5, 128 for codec 4, each
used by the textures after it until the next). The others unpack halfwords: the top bit set copies an earlier
run (length in the low five bits), clear it is one or two texels in the codec's own packing:

  1 RGBA16, 2 RGBA32 (four bits a channel), 3 and 6 IA8 (two texels), 4 IA16 (two texels through a 128-byte
  table), 5 RGBA32 (a 256-byte colour table and four bits of alpha).

The table names no dimensions; the game's code passes them. The width is inferred from the texels: at the true
width each texel is closest to the one below it, a dip that strides one shorter or longer don't share. Square
sizes are preferred when they score nearly as well. Checked against the dimensions a decompilation lists for one
release: 96% agree. The preview lets the width be changed.
"""
from __future__ import annotations

import math
import struct
from operator import sub

from .. import formats as asset_formats
from ..formats import AssetError

MAX_ENTRIES = 8192
MAX_PACKED = 64 * 1024
CODECS = {1: ('rgba5551-be', 2), 2: ('rgba8888', 4), 3: ('ia8', 1), 4: ('ia16', 2), 5: ('rgba8888', 4), 6: ('ia8', 1)}
TABLES = {4: 128, 5: 256}
NAMES = {'rgba5551-be': 'RGBA16', 'rgba8888': 'RGBA32', 'ia8': 'IA8', 'ia16': 'IA16'}
SQUARE_MARGIN = 1.3


def table(image, at):
    """The table's entries as (ROM offset, packed size, codec), or None when no table starts at `at`."""
    if at + 16 > len(image):return None
    first = int.from_bytes(image[at:at+4], 'big')
    count = first // 8
    if first % 8 or not 64 <= count <= MAX_ENTRIES or at + first > len(image):return None
    entries, expected, unchained = [], first, 0
    for offset, size, codec in struct.iter_unpack('>IHH', image[at:at+first]):
        if codec > 6 or at + offset + size > len(image):return None
        # A few placeholder entries point back at one shared resource; the rest must chain.
        if offset != expected:unchained += 1
        entries.append((at + offset, size, codec))
        expected = max(expected, offset + size + (-size) % 8)
    return entries if unchained * 20 <= count and sum(c for _, _, c in entries) else None


def _single(codec, word, lut):
    if codec == 1:return struct.pack('>H', (word & 0xFFC0) << 1 | word & 0x3F)
    if codec == 2:
        return struct.pack('>I', (word & 0x7800) << 17 | (word & 0x0780) << 13 | (word & 0x78) << 9 | (word & 7) << 5)
    if codec == 3:return bytes((((word >> 8) << 1) & 0xFF, ((word & 0xFF) << 1) & 0xFF))
    if codec == 6:
        high, low = word >> 8, word & 0xFF
        return bytes(((high & 0x38) << 2 | (high & 7) << 1, (low & 0x38) << 2 | (low & 7) << 1))
    if codec == 4:
        high, low = word >> 8, word & 0xFF
        a = int.from_bytes(lut[high & 0xFE:(high & 0xFE)+2], 'big') << 1 | high & 1
        b = int.from_bytes(lut[low & 0xFE:(low & 0xFE)+2], 'big') << 1 | low & 1
        return struct.pack('>HH', a & 0xFFFF, b & 0xFFFF)
    colour = int.from_bytes(lut[(word >> 4) << 1:((word >> 4) << 1)+2], 'big')
    return struct.pack('>I', ((colour & 0x7C00) << 17 | (colour & 0x03E0) << 14 | (colour & 0x1F) << 11 | (word & 0xF) << 4)
                       & 0xFFFFFFFF)


def unpack(codec, packed, lut=b''):
    """A texture's texels, unpacked; AssetError when a back-reference reaches outside them."""
    if codec in TABLES and len(lut) != TABLES[codec]:raise AssetError('This texture\'s colour table is missing. Rescan the ROM.')
    element = 4 if codec in (2, 4, 5) else 2
    mask, shift = (0x7FE0, 4) if element == 4 else (0x7FFF, 5)
    out = bytearray()
    for (word,) in struct.iter_unpack('>H', packed[:len(packed) & ~1]):
        if word & 0x8000:
            start = len(out) - ((word & mask) >> shift)
            length = (word & 0x1F) * element
            if start < 0 or start + length > len(out):raise AssetError('The packed texture is not valid here. Rescan the ROM.')
            out += out[start:start+length]
        else:out += _single(codec, word, lut)
    return bytes(out)


def _levels(texels, fmt, count):
    """One brightness value per texel (the sum of its RGBA), for comparing texels."""
    pixels = asset_formats._rgba(texels, fmt, count)
    return [sum(pixels[i:i+4]) for i in range(0, 4*count, 4)]


def width(texels, fmt, bytes_per_texel):
    """The inferred width, and the candidate widths with their scores (lower is better)."""
    count = len(texels) // bytes_per_texel
    candidates = [w for w in range(4, 257, 4) if count % w == 0 and 2 <= count // w <= 256 and w <= 8*(count//w) and count//w <= 8*w]
    if not candidates:return None, {}
    levels = _levels(texels, fmt, count)

    def mean(stride):
        n = count - stride
        return sum(map(abs, map(sub, levels[stride:], levels[:n]))) / n if n > 0 else 0.0
    scores = {}
    for w in candidates:
        here = mean(w)
        # How well rows line up (the difference to the texel below), times how much better than a stride off by one.
        scores[w] = here * (here + 1) / (min(mean(w-1), mean(w+1)) + 1)
    best = min(scores, key=scores.get)
    side = math.isqrt(count)
    if side*side == count and side in scores and scores[side] <= SQUARE_MARGIN * scores[best]:best = side
    return best, scores


def regions(image, *, check=lambda: None, progress=lambda _: None):
    """One region per packed texture in a texture table, its width inferred from its texels."""
    for at in range(0, len(image) - 16, 8):
        if not at & 0xFFFF:check()
        if image[at] or image[at+1] or image[at+6] or image[at+7] > 6:continue
        entries = table(image, at)
        if entries:break
    else:return []
    results, luts = [], {}
    for index, (offset, size, codec) in enumerate(entries):
        if index % 128 == 0:
            check();progress(dict(phase='Reading the texture table', done=index, total=len(entries)))
        if codec == 0:
            for wanted, length in TABLES.items():
                if size == length:luts[wanted] = offset
            continue
        if not size or size > MAX_PACKED or (codec in TABLES and codec not in luts):continue
        lut = image[luts[codec]:luts[codec]+TABLES[codec]] if codec in TABLES else b''
        try:texels = unpack(codec, image[offset:offset+size], lut)
        except AssetError:continue
        fmt, per = CODECS[codec]
        best, _scores = width(texels, fmt, per)
        if not best:continue
        height = len(texels) // per // best
        settings = dict(format=fmt, width=best, height=height, offset=0)
        results.append(dict(offset=offset, size=size, kind='image', confidence='inferred', layout='blast',
                            label=f'Texture {index} · {NAMES[fmt]} {best}×{height}', table=at, entry=index, codec=codec,
                            lut=luts.get(codec), preview_settings={**settings, 'source': 'rom', 'offset': offset},
                            frames=1, palettes=0, frame_offsets=[0], palette_offsets=[], palette_entries=[],
                            levels=[dict(width=best, height=height, offset=0)],
                            reason=f'Entry {index} of the texture table at {at:#x}, unpacked with codec {codec} to exactly its '
                                   'texels. The table names no dimensions: the width is inferred from where rows line up. '
                                   'Runtime use is not established.'))
    return results


def preview(image, asset, selection):
    """Unpack the texture again and show it at the inferred width, or the width chosen."""
    entries = table(image, asset['table'])
    if not entries or asset['entry'] >= len(entries) or entries[asset['entry']][0] != asset['offset']:
        raise AssetError('The texture table changed. Rescan the ROM.')
    _, size, codec = entries[asset['entry']]
    lut = image[asset['lut']:asset['lut']+TABLES[codec]] if codec in TABLES and asset.get('lut') is not None else b''
    texels = unpack(codec, image[asset['offset']:asset['offset']+size], lut)
    fmt, per = CODECS[codec]
    count = len(texels) // per
    chosen = asset_formats.integer(selection.get('width', asset['preview_settings']['width']), 'Width', 1, count)
    if count % chosen:raise AssetError(f'Choose a width that divides the texture\'s {count} texels.')
    asset_formats.integer(selection.get('frame', 0), 'Frame', 0, 0)
    asset_formats.integer(selection.get('mip', 0), 'Mip level', 0, 0)
    result = asset_formats.preview(texels, dict(format=fmt, width=chosen, height=count // chosen, offset=0))
    result['details'].update(texture=0, frame=0, palette='none', note=asset['reason'])
    result['decoded'] = dict(codec=f'texture codec {codec}', bytes=len(texels), block_offset=asset['offset'], member=f"entry {asset['entry']}")
    result['settings'] = dict(source='rom', format='auto', offset=asset['offset'], texture=0, frame=0, palette=0, mip=0)
    return result
