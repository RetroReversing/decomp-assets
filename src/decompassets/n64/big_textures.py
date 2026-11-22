"""Indexed image packs in a bounded paged resource archive."""

import re
import struct

from .. import formats
from . import big_pages

LAYOUT = 'big-resource-images'


def _frames(data, start, size):
    if start + size > len(data) or size < 16:
        return []
    count, palette = struct.unpack_from('>2I', data, start)
    if (not 1 <= count <= 512 or not 8 + count * 8 <= palette <= size - 512):
        return []
    rows = [struct.unpack_from('>4BI', data, start + 8 + index * 8) for index in range(count)]
    if (any(not w or not h or not 8 + count * 8 <= offset < palette for w, h, _, _, offset in rows)
            or any(left[4] >= right[4] for left, right in zip(rows, rows[1:]))):
        return []
    frames = []
    for index, (tiles, height, kind, bank, offset) in enumerate(rows):
        width = tiles * 8
        bits = 8 if kind & 1 else 4
        end = rows[index+1][4] if index + 1 < count else palette
        length = width * height * bits // 8
        if end - offset != length or (bits == 4 and bank > 15) or (bits == 8 and bank):
            continue
        frames.append((offset, width, height, bits, palette + (bank * 32 if bits == 4 else 0)))
    return frames if len(frames) * 2 >= count else []


def from_archive(image, archive, data, check=lambda: None):
    result = []
    for match in re.finditer(b'PKG\0', data):
        at = match.start()
        if at + 16 > len(data):
            continue
        size, = struct.unpack_from('<I', data, at + 4)
        frames = _frames(data, at + 8, size)
        if not frames:
            continue
        lo, hi = big_pages.physical(archive, at, size + 8)
        result.append(dict(offset=lo, size=hi-lo, kind='image', layout=LAYOUT, confidence='validated',
                           label=f'Paged texture pack ({len(frames)} images)', frames=len(frames),
                           width=frames[0][1], height=frames[0][2], archive=archive[0], resource=at,
                           resource_size=size, reason='A paged resource contains bounded indexed images and their palette.',
                           preview_settings=dict(source='rom', format='auto', offset=lo, frame=0)))
        check()
    return result


def merge(assets):
    """Keep every pack selectable when several start in the same ROM page."""
    groups = {}
    for asset in assets:
        key = asset['archive'], asset['offset']
        member = dict(resource=asset['resource'], resource_size=asset['resource_size'], frames=asset['frames'])
        if key not in groups:
            groups[key] = dict(asset, members=[member])
        else:
            group = groups[key]
            group['members'].append(member)
            group['frames'] += asset['frames']
            group['size'] = max(group['size'], asset['size'])
            group['label'] = f"Paged texture packs ({group['frames']} images)"
    return list(groups.values())


def preview(image, asset, selection):
    archive = next((item for item in big_pages.archives(image) if item[0] == asset['archive']), None)
    members = asset.get('members') or [asset]
    frame = formats.integer(selection.get('frame', 0), 'Frame', 0, asset['frames'] - 1)
    selected = frame
    member = None
    for item in members:
        if selected < item['frames']:
            member = item
            break
        selected -= item['frames']
    if not archive or not member or not (data := big_pages.extract(
            image, archive, member['resource'], member['resource_size'] + 8)):
        raise formats.AssetError('The texture archive changed. Rescan ROM Explorer.')
    frames = _frames(data, 8, member['resource_size'])
    if selected >= len(frames):
        raise formats.AssetError('The texture pack changed. Rescan ROM Explorer.')
    offset, width, height, bits, palette = frames[selected]
    row_size = width * bits // 8
    raw = data[8+offset:8+offset+row_size*height]
    pixels = b''.join(raw[row:row+row_size] for row in range(len(raw)-row_size, -1, -row_size))
    colors = data[8+palette:8+palette+(32 if bits == 4 else 512)]
    result = formats.preview(pixels + colors, dict(format='ci4' if bits == 4 else 'ci8', offset=0,
                                                   width=width, height=height, palette_offset=len(pixels),
                                                   palette_format='rgba5551-be'))
    result['settings'] = dict(asset['preview_settings'], frame=frame)
    result['details']['note'] = asset['reason']
    return result
