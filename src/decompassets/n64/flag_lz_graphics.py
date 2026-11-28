"""Graphics in a bounded flag-byte compressed cartridge directory."""
import struct

from .. import formats
from . import display_lists, display_meshes

TEXTURES = 'flag-lz-textures'
MODELS = 'flag-lz-models'
_LIMIT = 4 * 1024 * 1024


def unpack(source):
    if len(source) < 5 or source[0] != 1:
        return None
    expected = int.from_bytes(source[1:4], 'big')
    if not 0 < expected <= _LIMIT:
        return None
    at, out = 4, bytearray()
    while at < len(source) and len(out) <= expected:
        flags = source[at]; at += 1
        if not flags:
            if at+8 > len(source) or len(out)+8 > expected:
                return None
            out.extend(source[at:at+8]); at += 8
            continue
        for bit in range(7, -1, -1):
            if not flags & (1 << bit):
                if at >= len(source) or len(out) >= expected:
                    return None
                out.append(source[at]); at += 1
                continue
            if at+2 > len(source):
                return None
            hi, lo = source[at:at+2]; at += 2
            distance = ((hi & 0xf0) << 4) | lo
            if not distance:
                return bytes(out) if len(out) == expected else None
            count = hi & 15
            if not count:
                if at >= len(source):
                    return None
                count = source[at]+17; at += 1
            else:
                count += 1
            if distance > len(out) or len(out)+count > expected:
                return None
            for _ in range(count):
                out.append(out[-distance])
    return None


def directories(image, check=lambda: None):
    """Require consecutive aligned extent pairs and multiple complete streams."""
    stop = min(len(image)-32, 0x200000)
    skip = 0
    for at in range(0x1000, stop, 4):
        if at < skip:
            continue
        if not at % 0x4000:
            check()
        first, end, following = struct.unpack_from('>3I', image, at)
        if not (at+64 <= first < end <= len(image) and first-at <= 0x100000
                and first % 16 == end % 16 == 0 and following == end and image[first] == 1):
            continue
        rows = []
        for pos in range(at, min(first, at+8*4096), 8):
            lo, hi = struct.unpack_from('>II', image, pos)
            if not (0 < lo < hi <= len(image) and lo % 16 == hi % 16 == 0
                    and (not rows or lo == rows[-1][1])):
                break
            rows.append((lo, hi))
        if len(rows) < 8:
            continue
        checked = [unpack(image[lo:hi]) for lo, hi in rows[:8] if image[lo] == 1]
        if len(checked) < 4 or any(data is None for data in checked):
            continue
        skip = at+8*len(rows)
        yield rows


def _extra_state(w0, w1):
    # Local previews omit object matrices and calls into separately loaded segments.
    return ((w0 == 0xda380000 and w1 >> 24 == 3 and not w1 & 63)
            or (w0, w1) == (0xd8380002, 0x40)
            or (w0 == 0xde000000 and w1 >> 24 in (3, 4)))


def _local_list(data, start):
    """Omit triangles whose vertex cache may have been changed by an external list."""
    end = next((at+8 for at in range(start, min(len(data)-7, start+4096*8), 8)
                if data[at:at+8] == b'\xdf\0\0\0\0\0\0\0'), None)
    if end is None:
        return None
    local = bytearray(data)
    loaded = set()
    for at in range(start, end, 8):
        w0, w1 = struct.unpack_from('>II', data, at)
        cmd = w0 >> 24
        if cmd == 0xde:
            loaded.clear()
        elif cmd == 1:
            count = display_lists._vertex_count(w0)
            dest = ((w0 >> 1) & 127) - count
            loaded.update(range(dest, dest+count))
        elif cmd in (5, 6, 7):
            words = (w0,) if cmd == 5 else (w0, w1)
            slots = [(word >> shift) & 255 for word in words for shift in (16, 8, 0)]
            if any(slot & 1 or slot//2 not in loaded for slot in slots):
                local[at:at+8] = b'\xe7\0\0\0\0\0\0\0'
    return local, end


def discover(data):
    """Only list starts named in the segment-two resource header are candidates."""
    if len(data) < 96:
        return [], []
    pointers = {word & 0xffffff for word, in struct.iter_unpack('>I', data[:min(64, len(data))])
                if word >> 24 == 2 and not word & 7 and (word & 0xffffff) < len(data)-8}
    meshes, textures, seen = [], [], set()
    for start in sorted(pointers):
        prepared = _local_list(data, start)
        if not prepared:
            continue
        local, stop = prepared
        parsed = display_meshes.geometry(local, start, stop, {2: 0}, extra_state=_extra_state)
        if not parsed:
            continue
        end, vertices, faces = parsed
        if len(vertices) < 3 or not faces:
            continue
        meshes.append(dict(label=f'Mesh {len(meshes)+1}', model_offset=start, model_size=end-start,
                           vertices=len(vertices), triangles=len(faces)))
        boundaries = [start] + [at+8 for at in range(start, end-8, 8) if data[at] == 0xde] + [end]
        found = (item for lo, hi in zip(boundaries, boundaries[1:]) if hi-lo >= 16
                 for item in display_lists._textures(data[:hi], dict(start=lo, end=hi-8)))
        for item in found:
            if not start <= item['at'] < end:
                continue
            if item['space'] != 2 or item.get('swapped'):
                continue
            offset, size = item['address'], item['bytes']
            if offset+size > len(data):
                continue
            settings = dict(format=item['fmt'], width=item['width'], height=item['height'], offset=offset)
            if item.get('palette_space') is not None:
                pal = item.get('palette_address')
                count = item.get('palette_entries', 0)
                full = 16 if item['fmt'] == 'ci4' else 256
                if (item['palette_space'] != 2 or not isinstance(pal, int) or pal+full*2 > len(data)
                        or item['fmt'] == 'ci8' and max(data[offset:offset+size], default=0) >= count):
                    continue
                if item['fmt'] == 'ci4' and count < 16 and any(
                        max(byte >> 4, byte & 15) >= count for byte in data[offset:offset+size]):
                    continue
                settings.update(palette_offset=pal, palette_format=item['palette_format'])
            key = tuple(settings.items())
            if key not in seen:
                seen.add(key); textures.append(dict(preview_settings=settings, frames=1,
                    palettes=int('palette_offset' in settings), levels=[dict(width=item['width'], height=item['height'], offset=0)]))
    return meshes, textures


def regions(image, *, check=lambda: None, **kwargs):
    result = []
    for rows in directories(image, check):
        for index, (start, end) in enumerate(rows):
            if not index % 16:
                check()
            if image[start] != 1 or end-start < 5:
                continue
            size = int.from_bytes(image[start+1:start+4], 'big')
            if not 0 < size <= _LIMIT:
                continue
            data = unpack(image[start:end])
            if not data:
                continue
            meshes, textures = discover(data)
            common = dict(offset=start, size=end-start, unpacked=size, confidence='validated',
                          preview_settings=dict(format='auto', source='rom', offset=start))
            if meshes:
                result.append(dict(**common, kind='3d model', media='model', layout=MODELS,
                    label=f'{len(meshes)} compressed display-list meshes', meshes=meshes,
                    vertices=sum(x['vertices'] for x in meshes), triangles=sum(x['triangles'] for x in meshes),
                    reason='A bounded directory member names closed display lists with local vertex and triangle data.'))
            if textures:
                image_common = dict(common, preview_settings=dict(common['preview_settings'],
                    width=textures[0]['preview_settings']['width'], height=textures[0]['preview_settings']['height']))
                result.append(dict(**image_common, kind='image', media='image', layout=TEXTURES,
                    label=f'{len(textures)} compressed display-list textures', textures=textures, texture_count=len(textures),
                    frames=1, palettes=1, levels=[],
                    reason='Closed display lists in a bounded directory member load these local pixels and palettes.'))
    return result


def preview(image, asset, selection):
    data = unpack(image[asset['offset']:asset['offset']+asset['size']])
    if data is None or len(data) != asset['unpacked']:
        raise formats.AssetError('The compressed resource changed. Scan ROM Explorer again.')
    meshes, textures = discover(data)
    if asset['layout'] == MODELS:
        index = formats.integer(selection.get('mesh', 0), 'Model', 0, len(meshes)-1)
        if meshes != asset['meshes']:
            raise formats.AssetError('The display lists changed. Scan ROM Explorer again.')
        item = meshes[index]
        local = dict(offset=item['model_offset'], size=item['model_size'], address_maps=[(2, 0)],
                     label=item['label'], vertex_end=len(data), preview_settings=asset['preview_settings'])
        prepared = _local_list(data, item['model_offset'])
        if not prepared:
            raise formats.AssetError('The display list changed. Scan ROM Explorer again.')
        result = display_meshes.preview(prepared[0], local, selection, extra_state=_extra_state)
        result['note'] = ('Local geometry only. Triangles after external calls are omitted until another local vertex load; '
                          'object transforms, materials and external lists are separate.')
        return result
    index = formats.integer(selection.get('texture', 0), 'Texture', 0, len(textures)-1)
    if textures != asset['textures']:
        raise formats.AssetError('The texture lists changed. Scan ROM Explorer again.')
    result = formats.preview(data, textures[index]['preview_settings'])
    result['details'].update(texture=index, note=asset['reason'])
    result['settings'] = dict(asset['preview_settings'], texture=index, frame=0, palette=0, mip=0)
    return result
