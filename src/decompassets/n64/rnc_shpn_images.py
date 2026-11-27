"""SHPN image banks inside checksum-verified RNC containers."""
import re
import struct

from .. import formats, rnc
from . import shpn_images

LAYOUT = 'rnc-shpn-images'
_MAX_EXPANDED = 64 * 1024 * 1024


def _unpack(image, start, size):
    if not 0 <= start <= len(image)-size or size < rnc.HEADER_BYTES:
        return None
    data = image[start:start+size]
    try:
        if data[:4] == b'RNC\x01':
            return rnc.unpack(data, max_output=formats.MAX_BYTES)
        if data[:4] == b'RNC\x02':
            return rnc.unpack_m2(data, max_output=formats.MAX_BYTES)
    except rnc.RncError:
        return None
    return None


def regions(image, *, check=lambda: None, **kwargs):
    found = []
    expanded = 0
    for match in re.finditer(b'RNC[\x01\x02]', image):
        check()
        start = match.start()
        if start+18 > len(image):
            continue
        size, packed = struct.unpack_from('>II', image, start+4)
        extent = packed+18
        if not 0 < size <= formats.MAX_BYTES or not 0 < packed <= formats.MAX_BYTES or start+extent > len(image):
            continue
        if expanded+size > _MAX_EXPANDED:
            break
        expanded += size
        data = _unpack(image,start,extent)
        if not data:
            continue
        images = shpn_images.frames(data)
        if not images:
            continue
        alternate = shpn_images.frames(data,1)
        palettes = (2 if len(alternate)==len(images) and any(a[4] != b[4] for a,b in zip(images,alternate)) else 1) if any(a[5] != 16 for a in images) else 0
        found.append(dict(offset=start,size=extent,kind='image',layout=LAYOUT,
                          label=f'RNC SHPN texture bank ({len(images)} images)',confidence='validated',
                          frames=len(images),palettes=palettes,width=images[0][2],height=images[0][3],
                          reason='Both RNC checksums and the image and palette directory passed validation.',
                          preview_settings=dict(format='auto',source='rom',offset=start,frame=0,
                                                width=images[0][2],height=images[0][3])))
    return found


def preview(image, asset, selection):
    data = _unpack(image,asset['offset'],asset['size'])
    if data is None:
        raise formats.AssetError('The RNC image bank changed. Scan ROM Explorer again.')
    local = dict(asset,offset=0,size=len(data),layout=shpn_images.RAW_LAYOUT)
    result = shpn_images.preview(data,local,selection)
    result['settings'] = dict(asset['preview_settings'],frame=selection.get('frame',0),palette=selection.get('palette',0))
    return result
