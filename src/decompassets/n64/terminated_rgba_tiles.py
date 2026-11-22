"""Repeated legacy display-list terminators followed by fixed-size image tiles."""
import base64
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
        # A strong concentration of equal nibbles is evidence for indexed
        # pixels, not 16-bit colors. Ambiguous mixed runs are left unclassified.
        ratios = []
        for frame in range(count):
            pixels = image[start+8+frame*_STRIDE:start+_STRIDE+frame*_STRIDE]
            ratios.append(sum((value >> 4) == (value & 15) for value in pixels)/len(pixels))
        indexed = all(value >= .7 for value in ratios)
        if not indexed and not all(value <= .2 for value in ratios):
            continue
        reason = ('Repeated terminators bound 64 × 64 four-bit index tiles; grayscale shows indices because the palette is unresolved.'
                  if indexed else 'Repeated display-list terminators bound 2,048-byte tiles; 32 by 32 RGBA5551 is inferred.')
        result.append(dict(offset=start, size=count*_STRIDE, kind='image', media='image', layout=LAYOUT,
                           label=f'Indexed tile bank ({count} images)' if indexed else f'RGBA tile bank ({count} images)', confidence='inferred',
                           frames=count, width=64 if indexed else 32, height=64 if indexed else 32, indexed=indexed,
                           reason=reason,
                           preview_settings=dict(format='auto', source='rom', offset=start, frame=0)))
    return result


def preview(image, asset, selection):
    frame = formats.integer(selection.get('frame', 0), 'Frame', 0, asset['frames']-1)
    offset = asset['offset']+frame*_STRIDE
    if image[offset:offset+8] != _END:
        raise formats.AssetError('The tile bank changed. Rescan ROM Explorer.')
    if asset.get('indexed'):
        raw = image[offset+8:offset+_STRIDE]
        if len(raw) != 2048:
            raise formats.AssetError('The tile bank changed. Rescan ROM Explorer.')
        rgba = bytearray()
        for byte in raw:
            for index in (byte >> 4, byte & 15):
                rgba.extend((index*17, index*17, index*17, 255))
        result = dict(media='image', mime='image/png',
                      data_url='data:image/png;base64,'+base64.b64encode(formats._png(64, 64, rgba)).decode(),
                      details=dict(width=64, height=64, format='4-bit indices, grayscale'))
    else:
        result = formats.preview(image, dict(format='rgba5551-be', offset=offset+8, width=32, height=32))
    result['settings'] = dict(asset['preview_settings'], frame=frame)
    result['details']['note'] = asset['reason']
    return result
