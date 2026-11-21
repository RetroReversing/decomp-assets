"""Preview TIM textures and full-screen RGBA16 images from BIND archives."""

import base64
import struct

from .. import formats
from ..formats import AssetError
from . import bind

LAYOUT = 'bind-texture'
SCREEN_SIZE = 320*240*2


def _tim(data):
    if len(data) < 32:
        return None
    magic, flags = struct.unpack_from('<II',data)
    if magic != 0x10 or flags not in (8,9):
        return None
    colors = 16 if flags == 8 else 256
    palette_size, _, _, palette_width, palette_height = struct.unpack_from('<I4H',data,8)
    if palette_width != colors or palette_height != 1 or palette_size != 12+colors*2:
        return None
    at = 8+palette_size
    if at+12 > len(data):
        return None
    image_size, _, _, width_words, height = struct.unpack_from('<I4H',data,at)
    width = width_words*(4 if flags == 8 else 2)
    if not 0 < width <= 1024 or not 0 < height <= 1024:
        return None
    end = at+image_size
    if image_size != 12+width_words*height*2 or end != len(data):
        return None
    return ('ci4' if flags == 8 else 'ci8'),width,height,memoryview(data)[20:at],memoryview(data)[at+12:end]


def sprite_pairs(members):
    by_name = {}
    for member in members:
        by_name.setdefault(member.name.upper(),[]).append(member)
    pairs = {}
    for name, rows in by_name.items():
        matches = by_name.get(name[:-4]+'A.PAK',())
        if len(rows) == len(matches) == 1 and rows[0].unpacked == 2048 and matches[0].unpacked == 1024:
            pairs[rows[0]], pairs[matches[0]] = matches[0], rows[0]
    return pairs


def asset(data, member, *, screen, pair=None):
    if screen:
        name, width, height = 'rgba5551-be',320,240
    elif pair:
        name, width, height = ('i8' if member.unpacked==1024 else 'rgba5551-be'),32,32
    elif tim := _tim(data):
        name, width, height = tim[:3]
    else:
        return None
    reason = 'The PACK member expands to a TIM image with exact palette and pixel blocks.'
    if screen:
        reason = 'A packed full-screen RGBA16 image in a directory of complete frames.'
    elif pair:
        reason = 'The named sprite and its matching alpha plane expand to exact 32 × 32 pixel blocks.'
    return dict(offset=member.offset,size=member.size,kind='image',layout=LAYOUT,frames=1,
                confidence='validated',label=member.name,screen=screen,
                alpha=[pair.offset,pair.size] if pair and member.unpacked==2048 else None,
                mask=bool(pair and member.unpacked==1024),
                preview_settings=dict(format=name,source='rom',offset=member.offset,width=width,height=height),
                reason=reason)


def _tim_pixels(tim):
    name, width, height, palette, texels = tim
    colors = []
    for color, in struct.iter_unpack('<H',palette):
        colors.append(bytes(((color&31)*255//31,((color>>5)&31)*255//31,
                             ((color>>10)&31)*255//31,255 if color else 0)))
    if name == 'ci4':
        pixels = b''.join(colors[value&15]+colors[value>>4] for value in texels)
    else:
        pixels = b''.join(colors[value] for value in texels)
    return width,height,pixels


def preview(image, asset, selection):
    offset = asset['offset']
    data = bind.unpack(image[offset:offset+asset['size']])
    if asset.get('screen') and len(data) == SCREEN_SIZE:
        width,height = 320,240
        pixels = formats._rgba(data,'rgba5551-be',width*height)
    elif asset.get('mask') and len(data) == 1024:
        width = height = 32
        pixels = formats._rgba(data,'i8',1024)
    elif asset.get('alpha') and len(data) == 2048:
        start, size = asset['alpha']
        alpha = bind.unpack(image[start:start+size])
        if len(alpha) != 1024:
            raise AssetError('The BIND sprite alpha plane changed. Scan ROM Explorer again.')
        width = height = 32
        pixels = bytearray(formats._rgba(data,'rgba5551-be',1024))
        pixels[3::4] = alpha
    elif tim := _tim(data):
        width,height,pixels = _tim_pixels(tim)
    else:
        raise AssetError('The BIND texture has changed. Scan ROM Explorer again.')
    encoded = base64.b64encode(formats._png(width,height,pixels)).decode()
    settings = {**asset['preview_settings'],'format':'auto'}
    return dict(media='image',data_url='data:image/png;base64,'+encoded,settings=settings,
                details=dict(width=width,height=height,note=asset['reason']),
                decoded=dict(codec='PACK',bytes=len(data),block_offset=offset,member=asset['label']))
