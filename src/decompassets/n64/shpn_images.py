"""Indexed images and palettes in bounded RefPack SHPN containers."""
from .. import formats, refpack

LAYOUT = 'refpack-shpn-images'


def frames(data):
    if len(data) < 16 or data[:4] != b'SHPN' or int.from_bytes(data[4:8], 'big') != len(data) or data[12:16] != b'GIMX':
        return []
    count = int.from_bytes(data[8:12], 'big')
    if not 1 <= count <= 1024 or 16+8*count > len(data):
        return []
    result = []
    for i in range(count):
        name = data[16+i*8:20+i*8].decode('ascii', errors='replace').strip()
        at = int.from_bytes(data[20+i*8:24+i*8], 'big')
        if at < 16+8*count or at+16 > len(data) or data[at] not in (0x63, 0x66):
            continue
        bits = 4 if data[at] == 0x63 else 8
        size = int.from_bytes(data[at+1:at+4], 'big')
        w = int.from_bytes(data[at+4:at+6], 'big')
        h = int.from_bytes(data[at+6:at+8], 'big')
        palette = at+size
        colors = 1 << bits
        if (not 1 <= w <= 1024 or not 1 <= h <= 1024 or w*h*bits % 8
                or size < 16+w*h*bits//8 or palette+16+colors*2 > len(data)
                or data[palette] != 0x27
                or int.from_bytes(data[palette+4:palette+6], 'big') != colors):
            continue
        result.append((name, at+16, w, h, palette+16, bits))
    return result


def regions(image, *, check=lambda: None, **kwargs):
    found = []
    at = 0
    while (at := image.find(b'\x10\xfb', at)) >= 0:
        start = at
        at += 2
        check()
        try:
            data, consumed = refpack.unpack(memoryview(image)[start:])
        except (ValueError, IndexError):
            continue
        images = frames(data)
        if not images:
            continue
        check()
        found.append(dict(offset=start, size=consumed, kind='image', layout=LAYOUT,
                          label=f'SHPN texture bank ({len(images)} images)', confidence='validated',
                          frames=len(images), width=images[0][2], height=images[0][3],
                          reason='The container bounds each indexed image and its adjacent palette.',
                          preview_settings=dict(format='auto', source='rom', offset=start, frame=0)))
    return found


def preview(image, asset, selection):
    try:
        data, _ = refpack.unpack(memoryview(image)[asset['offset']:])
    except (ValueError, IndexError) as error:
        raise formats.AssetError('The compressed texture changed. Rescan ROM Explorer.') from error
    images = frames(data)
    if not images:
        raise formats.AssetError('The texture bank changed. Rescan ROM Explorer.')
    index = formats.integer(selection.get('frame', 0), 'Frame', 0, len(images)-1)
    name, at, width, height, palette, bits = images[index]
    result = formats.preview(data, dict(format=f'ci{bits}', offset=at, width=width, height=height,
                                        palette_offset=palette, palette_format='rgba5551-be'))
    result['settings'] = {**asset['preview_settings'], 'frame': index}
    result['details'].update(name=name, note=asset['reason'])
    return result
