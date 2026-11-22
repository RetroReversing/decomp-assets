"""Repeated legacy display-list terminators followed by fixed-size image tiles."""
import re

from .. import formats

LAYOUT = 'terminated-rgba-tile-bank'
_STRIDE = 8+32*32*2
_END = b'\xb8'+bytes(7)


def regions(image, *, check=lambda: None, **kwargs):
    offsets = {m.start() for m in re.finditer(re.escape(_END), image) if m.start()%8 == 0}
    result = []
    for start in sorted(offsets):
        if start-_STRIDE in offsets or start+_STRIDE not in offsets:
            continue
        check()
        count = 0
        while start+(count+1)*_STRIDE in offsets and count < 1024:
            count += 1
        if count < 2:
            continue
        # The run establishes extents; color and dimensions remain inferred.
        result.append(dict(offset=start, size=count*_STRIDE, kind='image', media='image', layout=LAYOUT,
                           label=f'RGBA tile bank ({count} images)', confidence='inferred',
                           frames=count, width=32, height=32,
                           reason='Repeated display-list terminators bound 2,048-byte tiles; 32 by 32 RGBA5551 is inferred.',
                           preview_settings=dict(format='auto', source='rom', offset=start, frame=0)))
    return result


def preview(image, asset, selection):
    frame = formats.integer(selection.get('frame', 0), 'Frame', 0, asset['frames']-1)
    offset = asset['offset']+frame*_STRIDE
    if image[offset:offset+8] != _END:
        raise formats.AssetError('The tile bank changed. Rescan ROM Explorer.')
    result = formats.preview(image, dict(format='rgba5551-be', offset=offset+8, width=32, height=32))
    result['settings'] = dict(asset['preview_settings'], frame=frame)
    result['details']['note'] = asset['reason']
    return result
