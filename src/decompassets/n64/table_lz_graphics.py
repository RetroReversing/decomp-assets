"""Runtime graphics in bounded table-indexed 14-bit ring LZ streams."""
import struct

from .. import formats

TEXTURES = 'runtime-table-lz-textures'
MAX_EXPANDED = 4 * 1024 * 1024


def descriptors(image, check=lambda: None):
    """Four consecutive, aligned start/end pairs establish a bounded resource table."""
    found = set()
    for at in range(0, len(image)-31, 4):
        if at % 0x40000 == 0:
            check()
        a,b,c,d,e,f,g,h = struct.unpack_from('>8I', image, at)
        if (b != c or d != e or f != g or not 0x1000 <= a < b < d < f < h <= len(image)
                or (a | b | d | f | h) & 15 or max(b-a,d-b,f-d,h-f) > 0x100000):
            continue
        found.update(((a,b),(b,d),(d,f),(f,h)))
    return sorted(found)


def inflate(source, check=lambda: None):
    """MSB-first literal/absolute-ring tokens, terminated by the zero ring index."""
    pos = bit = 0
    ring = bytearray(16384)
    write = 1
    out = bytearray()
    next_check = 0
    def read(count):
        nonlocal pos, bit
        value = 0
        for _ in range(count):
            if pos >= len(source):
                raise EOFError
            value = value << 1 | (source[pos] >> (7-bit) & 1)
            bit += 1
            if bit == 8:
                bit = 0
                pos += 1
        return value
    try:
        while len(out) < MAX_EXPANDED:
            if len(out) >= next_check:
                check()
                next_check = len(out)+8192
            if read(1):
                value = read(8)
                out.append(value)
                ring[write] = value
                write = (write+1)&16383
                continue
            source_at = read(14)
            if not source_at:
                return bytes(out), pos + bool(bit)
            length = read(4)+3
            if len(out)+length > MAX_EXPANDED:
                return None
            for i in range(length):
                value = ring[(source_at+i)&16383]
                out.append(value)
                ring[write] = value
                write = (write+1)&16383
    except (IndexError, EOFError):
        pass
    return None


def preview(image, asset, selection):
    from . import block16_graphics, ring12_graphics, runtime_packed_graphics, textures
    start = asset['offset']
    packed = (block16_graphics.inflate(image[start:start+asset['size']]) if asset.get('codec') == 'block16'
              else runtime_packed_graphics.unpack_mio(image[start:start+asset['size']]) if asset.get('codec') == 'mio0'
              else runtime_packed_graphics.unpack_erz(image[start:start+asset['size']]) if asset.get('codec') == 'erz'
              else runtime_packed_graphics.unpack_rnc(image[start:start+asset['size']]) if asset.get('codec') == 'rnc'
              else ring12_graphics.inflate(image[start:start+asset['size']]) if asset.get('codec') == 'ring12'
              else inflate(image[start:start+asset['size']]))
    if not packed or packed[1] != asset['size']:
        raise formats.AssetError('The packed graphics block changed. Scan ROM Explorer again.')
    data, _ = packed
    index = formats.integer(selection.get('texture', 0), 'Texture', 0, len(asset['textures'])-1)
    item = asset['textures'][index]
    options = item['preview_settings']
    if item['swapped']:
        offset = options['offset']
        row = item['texel_bytes']//options['height']
        pixels = bytearray(data[offset:offset+item['texel_bytes']])
        for line in range(row,len(pixels),2*row):
            for word in range(line,line+row,8):
                pixels[word:word+8] = pixels[word+4:word+8]+pixels[word:word+4]
        data = data[:offset]+pixels+data[offset+len(pixels):]
    result = textures.preview(data, {**item,'offset':start,'reason':asset['reason']}, {})
    result['settings'] = dict(source='rom',format='auto',offset=start,texture=index)
    codec = {'ring12': '12-bit ring LZ', 'mio0': 'MIO0', 'erz': 'ERZ', 'block16': '16-bit control LZ/RLE'}.get(asset.get('codec'), '14-bit ring LZ')
    result['decoded'] = dict(codec=codec,bytes=len(data),block_offset=start,member=asset['label'])
    return result
