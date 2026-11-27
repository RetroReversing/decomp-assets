"""Indexed images and palettes in bounded RefPack SHPN containers."""
from .. import formats, refpack

LAYOUT = 'refpack-shpn-images'
RAW_LAYOUT = 'shpn-images'


def frames(data, palette_index=0):
    if len(data) < 16 or data[:4] != b'SHPN' or int.from_bytes(data[4:8], 'big') != len(data) or data[12:16] != b'GIMX':
        return []
    count = int.from_bytes(data[8:12], 'big')
    if not 1 <= count <= 1024 or 16+8*count > len(data):
        return []
    entries = [(data[16+i*8:20+i*8],int.from_bytes(data[20+i*8:24+i*8], 'big')) for i in range(count)]
    offsets = [at for _,at in entries]
    # Shared palettes are identified by the directory, not by proximity or a guessed color table.
    shared = []
    if offsets == sorted(set(offsets)) and all(16+8*count <= at < len(data) for at in offsets):
        for name in (b'pal ',b'cpal'):
            candidates = [(i,at) for i,(tag,at) in enumerate(entries) if tag == name]
            if len(candidates) != 1:
                continue
            i,at = candidates[0]
            end = offsets[i+1] if i+1 < count else len(data)
            if at+16 <= end and data[at] == 0x27:
                colors = int.from_bytes(data[at+4:at+6], 'big')
                if colors in (16,256) and at+16+colors*2 <= end:
                    shared.append((name,at+16,colors))
    result = []
    decoded_total = 0
    for i in range(count):
        name = data[16+i*8:20+i*8].decode('ascii', errors='replace').strip()
        at = int.from_bytes(data[20+i*8:24+i*8], 'big')
        if at < 16+8*count or at+16 > len(data) or data[at] not in (0x63, 0x66, 0xe3, 0xe6):
            continue
        bits = 4 if data[at] in (0x63, 0xe3) else 8
        compressed = bool(data[at] & 0x80)
        size = int.from_bytes(data[at+1:at+4], 'big')
        w = int.from_bytes(data[at+4:at+6], 'big')
        h = int.from_bytes(data[at+6:at+8], 'big')
        colors = 1 << bits
        if not 1 <= w <= 1024 or not 1 <= h <= 1024:
            continue
        pixel_bytes = ((w*bits+7)//8)*h
        if size:
            palette = at+size
            if (size < 16 or palette+16+colors*2 > len(data)
                    or data[palette] != 0x27
                    or int.from_bytes(data[palette+4:palette+6], 'big') != colors):
                continue
            if compressed:
                if at+21 > palette:
                    continue
                declared = int.from_bytes(data[at+18:at+21], 'big')
                if not pixel_bytes <= declared <= pixel_bytes+15:
                    continue
                decoded_total += declared
                if decoded_total > formats.MAX_BYTES:
                    return []
                try:
                    raw, used = refpack.unpack(memoryview(data)[at+16:palette])
                except (ValueError, IndexError):
                    continue
                if not pixel_bytes <= len(raw) <= pixel_bytes+15 or any(raw[pixel_bytes:]) or palette-(at+16+used) > 15:
                    continue
            elif size < 16+pixel_bytes:
                continue
            palette += 16
        else:
            # Zero-sized image headers use the next directory entry as their
            # bound and a named shared palette; extra bytes may hold mip levels.
            if (compressed or not shared or offsets != sorted(set(offsets)) or i+1 >= count
                    or at+16+pixel_bytes > offsets[i+1]):
                continue
            wanted = b'pal ' if palette_index == 0 else b'cpal'
            choices = [position for tag,position,n in shared if tag == wanted and n == colors]
            if len(choices) != 1:
                continue
            palette = choices[0]
        result.append((name, at+16, w, h, palette, bits, compressed, size))
    return result


def regions(image, *, check=lambda: None, **kwargs):
    found = []
    compressed_ranges = []
    at = 0
    while (at := image.find(b'\x10\xfb', at)) >= 0:
        start = at
        at += 2
        check()
        try:
            data, consumed = refpack.unpack(memoryview(image)[start:])
        except (ValueError, IndexError):
            continue
        compressed_ranges.append((start, start+consumed))
        images = frames(data)
        if not images:
            continue
        check()
        alternate = frames(data,1)
        palettes = 2 if len(alternate) == len(images) and any(a[4] != b[4] for a,b in zip(images,alternate)) else 1
        found.append(dict(offset=start, size=consumed, kind='image', layout=LAYOUT,
                          label=f'SHPN texture bank ({len(images)} images)', confidence='validated',
                          frames=len(images), palettes=palettes, width=images[0][2], height=images[0][3],
                          reason='The container bounds each indexed image and its inline or named shared palette.',
                          preview_settings=dict(format='auto', source='rom', offset=start, frame=0)))
    at = 0
    while (at := image.find(b'SHPN', at)) >= 0:
        start = at
        at += 4
        if any(lo <= start < hi for lo, hi in compressed_ranges) or start+16 > len(image):
            continue
        check()
        size = int.from_bytes(image[start+4:start+8], 'big')
        if not 16 <= size <= formats.MAX_BYTES or start+size > len(image):
            continue
        data = image[start:start+size]
        images = frames(data)
        if not images:
            continue
        alternate = frames(data, 1)
        palettes = 2 if len(alternate) == len(images) and any(a[4] != b[4] for a,b in zip(images,alternate)) else 1
        found.append(dict(offset=start, size=size, kind='image', layout=RAW_LAYOUT,
                          label=f'SHPN texture bank ({len(images)} images)', confidence='validated',
                          frames=len(images), palettes=palettes, width=images[0][2], height=images[0][3],
                          reason='The container bounds each indexed image and its inline or named shared palette.',
                          preview_settings=dict(format='auto', source='rom', offset=start, frame=0)))
        at = start+size
    return found


def preview(image, asset, selection):
    if asset.get('layout') == RAW_LAYOUT:
        data = image[asset['offset']:asset['offset']+asset['size']]
    else:
        try:
            data, _ = refpack.unpack(memoryview(image)[asset['offset']:])
        except (ValueError, IndexError) as error:
            raise formats.AssetError('The compressed texture changed. Rescan ROM Explorer.') from error
    palette = formats.integer(selection.get('palette',0),'Palette',0,asset.get('palettes',1)-1)
    images = frames(data,palette)
    if not images or len(images) != asset['frames']:
        raise formats.AssetError('The texture bank changed. Rescan ROM Explorer.')
    index = formats.integer(selection.get('frame', 0), 'Frame', 0, len(images)-1)
    name, at, width, height, palette, bits, compressed, size = images[index]
    if compressed:
        raw, _ = refpack.unpack(memoryview(data)[at:at+size-16])
        colors = 1 << bits
        pixels = bytes(raw) + bytes(data[palette:palette+colors*2])
        result = formats.preview(pixels, dict(format=f'ci{bits}', offset=0, width=width, height=height,
                                              palette_offset=len(raw), palette_format='rgba5551-be'))
    else:
        result = formats.preview(data, dict(format=f'ci{bits}', offset=at, width=width, height=height,
                                            palette_offset=palette, palette_format='rgba5551-be'))
    result['settings'] = {**asset['preview_settings'], 'frame': index, 'palette': palette}
    note = asset['reason'] + (' Pixel bytes were decoded from a bounded RefPack stream.' if compressed else '')
    result['details'].update(name=name, note=note)
    return result
