"""Indexed 64-by-64 CI4 pictures referenced by a validated level directory."""
import re
import struct

from .. import formats

LAYOUT = 'level-directory-logo'
# Table and picture layout: https://dsll32.github.io/nviewer/wiki/GEX3.html
_RECORD = 0x54
_NAME = re.compile(rb'[a-z0-9_]{2,16}\x00')


def records(image):
    """Find a run of bounded level records and resident, terminated names."""
    if len(image) < 0x2000:
        return []
    mapping = int.from_bytes(image[8:12], 'big') - 0x1000
    if not 0x7fff0000 <= mapping <= 0x80000000:
        return []
    for match in re.finditer(rb'\x80[\x00-\x0f]..', image[:min(len(image), 0x200000)], re.S):
        at = match.start()
        if at % 4:
            continue
        rows = []
        for pos in range(at, min(at+64*_RECORD, len(image)-_RECORD+1), _RECORD):
            name = struct.unpack_from('>I', image, pos)[0] - mapping
            lo, hi, code, end, ram_end, entry = struct.unpack_from('>6I', image, pos+0x1c)
            logo = struct.unpack_from('>I', image, pos+0x3c)[0]
            if (not 0 <= name < len(image)-17 or not (label := _NAME.match(image, name))
                    or not 0x1000 <= lo < hi <= len(image) or not 0x1000 <= code < end <= len(image)
                    or not 0x80000400 <= entry < ram_end <= 0x80800000
                    or not 0 <= logo <= len(image)-0x820):
                break
            rows.append(dict(name=label.group()[:-1].decode('ascii'), logo=logo, start=lo, end=hi))
        if len(rows) >= 8 and len({row['logo'] for row in rows if row['logo']}) >= 4:
            return rows
    return []


def regions(image, *, check=lambda: None, **kwargs):
    rows = records(image)
    result = []
    seen = set()
    for row in rows:
        name, at = row['name'], row['logo']
        check()
        if not at:
            continue
        if at in seen or not any(image[at:at+32]):
            continue
        seen.add(at)
        options = dict(offset=at+32, format='ci4', width=64, height=64,
                       palette_offset=at, palette_format='rgba5551-be')
        result.append(dict(offset=at, size=0x820, kind='image', media='image', layout=LAYOUT,
                           label=f'{name} logo', confidence='validated', preview_settings=options,
                           reason='A bounded level directory points to a CI4 picture and RGBA16 palette.'))
    return result


def preview(image, asset, selection):
    result = formats.preview(image, asset['preview_settings'])
    result['settings'] = asset['preview_settings']
    return result
