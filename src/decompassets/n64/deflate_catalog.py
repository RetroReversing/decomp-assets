"""Textures described by native catalog entries and stored in bounded zlib members."""

import re
import struct
import zlib

from .. import formats

TEXTURE = 'deflate-catalog-texture'
_ENTRY = struct.Struct('>3I18H')
_ENTRY_TAIL = re.compile(rb'\xff{4}\0{10}')
_OFFSET_MASK = 0xf0ffffff
_LIMIT = 4 * 1024 * 1024
_TEXTURES = {
    0: ('i4', 4), 3: ('ia4', 4), 4: ('ia8', 8),
    6: ('ci4', 4), 7: ('ci8', 8),
}


def bases(image, check):
    """Read cartridge bases added to a resource offset after masking its flags."""
    for match in re.finditer(rb'\x34\x21\xff\xff', image):
        at = match.start()
        if at < 32 or at % 4 or at + 20 > len(image):
            continue
        check()
        if 0x3c01f0ff not in (word for word, in struct.iter_unpack('>I', image[at - 32:at])):
            continue
        high, low, mask, add = struct.unpack_from('>4I', image, at + 4)
        base_reg = (high >> 16) & 31
        offset_reg = (mask >> 11) & 31
        if (not base_reg or high >> 21 != 0x1e0 or low >> 16 != 0x2400 | base_reg << 5 | base_reg
                or not offset_reg or mask & 0xfc0007ff != 0x24
                or 1 not in ((mask >> 21) & 31, (mask >> 16) & 31)
                or add & 0xfc00ffff != 0x2021
                or {(add >> 21) & 31, (add >> 16) & 31} != {offset_reg, base_reg}):
            continue
        base = ((high & 0xffff) << 16) + struct.unpack('>h', struct.pack('>H', low & 0xffff))[0]
        if 0 < base < len(image) and base % 4 == 0:
            yield base


def unpack(image, offset):
    """Read the decoded size and exact zlib stream size before inflating."""
    if not 0 <= offset <= len(image) - 8:
        return None
    length, packed = struct.unpack_from('>2I', image, offset)
    if not 0 < length <= _LIMIT or not 8 <= packed <= _LIMIT or offset + 8 + packed > len(image):
        return None
    decoder = zlib.decompressobj()
    try:
        data = decoder.decompress(image[offset + 8:offset + 8 + packed], length + 1)
    except zlib.error:
        return None
    if len(data) == length and decoder.eof and not decoder.unused_data:
        return 8 + packed, data


def _texture(image, record, base):
    if not 0 <= record <= len(image) - _ENTRY.size or not _ENTRY_TAIL.fullmatch(image[record + 34:record + 48]):
        return None
    relative, pointer, refs, width, height, _, _, _, _, frames, _, _, kind, *_ = _ENTRY.unpack_from(image, record)
    if pointer or refs or not relative or frames != 1 or kind not in _TEXTURES:
        return None
    if not (0 < width <= 512 and 0 < height <= 512):
        return None
    fmt, bits = _TEXTURES[kind]
    if width * bits % 8:
        return None
    pixels = width * height * bits // 8
    indexed = fmt in ('ci4', 'ci8')
    offset = base + (relative & _OFFSET_MASK)
    if offset % 4 or not (decoded := unpack(image, offset)):
        return None
    size, data = decoded
    if len(data) != pixels + (512 if indexed else 0):
        return None
    settings = dict(format=fmt, offset=0, width=width, height=height)
    if indexed:
        settings.update(palette_offset=pixels, palette_format='rgba5551-be')
    return offset, size, data, settings


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    archive_bases = sorted(set(bases(image, check)))
    if not archive_bases:
        return result
    for base in archive_bases:
        textures = {}
        for index, match in enumerate(_ENTRY_TAIL.finditer(image)):
            if index % 128 == 0:
                check()
            record = match.start() - 34
            if record % 4 or not (decoded := _texture(image, record, base)):
                continue
            offset, size, _, settings = decoded
            width, height = settings['width'], settings['height']
            palette = int('palette_offset' in settings)
            textures[offset] = dict(offset=offset, size=size, kind='image', layout=TEXTURE,
                                    archive_base=base, record=record, confidence='validated', frames=1, palettes=palette,
                                    label=f"{settings['format'].upper()} {width}×{height} texture",
                                    reason='The native texture entry supplies the dimensions and format, and the zlib checksum agrees.',
                                    levels=[dict(width=width, height=height, offset=0)],
                                    preview_settings=dict(source='rom', format='auto', offset=offset))
        if len(textures) >= 4:
            result.extend(textures.values())
    return result


def preview(image, asset, selection):
    decoded = _texture(image, asset['record'], asset['archive_base'])
    if not decoded or decoded[:2] != (asset['offset'], asset['size']):
        raise formats.AssetError('The compressed catalog texture changed. Rescan ROM Explorer.')
    offset, _, data, settings = decoded
    result = formats.preview(data, settings)
    result['details']['note'] = asset['reason']
    result['settings'] = dict(source='rom', format='auto', offset=offset, frame=0, palette=0, mip=0)
    result['decoded'] = dict(codec='zlib', bytes=len(data), block_offset=offset)
    return result
