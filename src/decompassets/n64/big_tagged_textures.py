"""Indexed texture sequences and palettes in paged tagged resources."""
import re
import struct

from .. import formats
from . import big_pages

LAYOUT = 'big-tagged-textures'


def _group(data, start):
    at, frames = start, []
    while at + 48 <= len(data) and data[at:at+8] == b'TEX\0\x14\0\0\0':
        width, height = struct.unpack_from('>HH', data, at+8)
        size, = struct.unpack_from('<I', data, at+40)
        end = at+44+size
        if (data[at+36:at+40] != b'BMP\0' or not 1 <= width <= 1024 or not 1 <= height <= 1024
                or size != width*height or end+4 > len(data) or any(data[end:end+4])):
            return None
        frames.append((at+44, width, height))
        if len(frames) > 512:
            return None
        at = end+4
    if (not frames or at+520 > len(data) or data[at:at+8] != b'PAL\0\0\x02\0\0'):
        return None
    return frames, at+8, at+520


def from_archive(image, archive, data, check=lambda: None):
    found, until = [], 0
    for match in re.finditer(b'TEX\0', data):
        at = match.start()
        if at < until:
            continue
        check()
        parsed = _group(data, at)
        if not parsed:
            continue
        frames, palette, until = parsed
        lo, hi = big_pages.physical(archive, at, until-at)
        found.append(dict(offset=lo, size=hi-lo, kind='image', layout=LAYOUT, confidence='validated',
                          label=f'Paged tagged textures ({len(frames)} images)', frames=len(frames), palettes=1,
                          width=frames[0][1], height=frames[0][2], archive=archive[0], resource=at,
                          resource_size=until-at, reason='Bounded tagged image dimensions and pixel lengths lead to a shared 256-colour palette.',
                          preview_settings=dict(source='rom', format='auto', offset=lo, frame=0,
                                                width=frames[0][1], height=frames[0][2])))
    groups = {}
    for asset in found:
        key = asset['offset']
        member = {k: asset[k] for k in ('resource', 'resource_size', 'frames')}
        if key not in groups:
            groups[key] = dict(asset, members=[member])
        else:
            group = groups[key]
            group['members'].append(member)
            group['frames'] += asset['frames']
            group['size'] = max(group['size'], asset['size'])
            group['label'] = f"Paged tagged textures ({group['frames']} images)"
    return list(groups.values())


def preview(image, asset, selection):
    archive = next((a for a in big_pages.archives(image) if a[0] == asset['archive']), None)
    frame = formats.integer(selection.get('frame', 0), 'Frame', 0, asset['frames']-1)
    selected = frame
    for member in asset['members']:
        if selected < member['frames']:
            break
        selected -= member['frames']
    else:
        raise formats.AssetError('The texture bank changed. Scan ROM Explorer again.')
    data = big_pages.extract(image, archive, member['resource'], member['resource_size']) if archive else None
    parsed = _group(data, 0) if data else None
    if not parsed or selected >= len(parsed[0]):
        raise formats.AssetError('The texture bank changed. Scan ROM Explorer again.')
    frames, palette, _ = parsed
    offset, width, height = frames[selected]
    pixels = data[offset:offset+width*height]
    colors = data[palette:palette+512]
    result = formats.preview(pixels+colors, dict(format='ci8', offset=0, width=width, height=height,
                                                palette_offset=len(pixels), palette_format='rgba5551-be'))
    result['settings'] = dict(asset['preview_settings'], frame=frame)
    result['details']['note'] = asset['reason']
    return result
