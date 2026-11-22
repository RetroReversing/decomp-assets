"""Named little-endian sound directories and their 20-byte ADPCM frames."""
import base64
import re
import struct

from .. import formats

LAYOUT = 'named-block-adpcm'
_NAME = re.compile(rb'[A-Za-z0-9_./-]{1,64}\.wav')
_STEPS = (7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45,
          50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190, 209, 230, 253,
          279, 307, 337, 371, 408, 449, 494, 544, 598, 658, 724, 796, 876, 963, 1060, 1166,
          1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327, 3660, 4026, 4428,
          4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442, 11487, 12635, 13899, 15289,
          16818, 18500, 20350, 22385, 24623, 27086, 29794, 32767)
_CHANGES = (-1, -1, -1, -1, 2, 4, 6, 8)


def directory(image, start):
    pos, expected, rows = start, 0, []
    while len(rows) < 4096:
        match = _NAME.match(image, pos, min(len(image), pos+80))
        if not match:
            break
        pos = match.end()
        if pos+8 > len(image):
            return None
        offset, size = struct.unpack_from('<II', image, pos)
        pos += 8
        if offset != expected or not 0 < size <= formats.MAX_BYTES or size % 20:
            return None
        expected += size
        if expected > len(image):
            return None
        rows.append((match.group().decode('ascii'), offset, size))
    base = (pos+3)&~3
    if (len(rows) < 3 or base+expected > len(image) or any(image[pos:base])
           ):
        return None
    # Each block has a predictor and a bounded step-index field.
    for _, offset, size in rows:
        for p in range(base+offset, base+offset+min(size, 20*8), 20):
            if int.from_bytes(image[p+2:p+4], 'big') & 0x7f > 88:
                return None
    return base, rows


def regions(image, *, check=lambda: None, **kwargs):
    found = []
    for match in _NAME.finditer(image):
        at = match.start()
        if at and image[at-1] in b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_./-':
            continue
        if match.end()+8 > len(image) or int.from_bytes(image[match.end():match.end()+4], 'little'):
            continue
        check()
        result = directory(image, at)
        if not result:
            continue
        base, rows = result
        samples = [dict(label=name, offset=base+offset, size=size, codec='Block ADPCM') for name, offset, size in rows]
        found.append(dict(offset=at, size=base-at, kind='audio', media='audio', layout=LAYOUT,
                          label=f'Named sound bank ({len(samples)} samples)', audio_kind='sample bank',
                          confidence='inferred', samples=samples, rate_basis='Nominal preview rate',
                          reason='Consecutive named entries bound 20-byte ADPCM frames; the nominal playback rate is adjustable.',
                          preview_settings=dict(format='auto', source='rom', offset=at, sample=0)))
    return found


def decode(raw, limit):
    out = bytearray()
    for at in range(0, len(raw)-19, 20):
        predictor, header = struct.unpack_from('>hH', raw, at)
        index = header & 0x7f
        if index >= len(_STEPS):
            raise formats.AssetError('The ADPCM block has an invalid step index.')
        for word, in struct.iter_unpack('>H', raw[at+4:at+20]):
            for _ in range(4):
                nibble = word & 15
                word >>= 4
                delta = _STEPS[index]*(nibble & 7)//4
                predictor += -delta if nibble & 8 else delta
                predictor = max(-32768, min(32767, predictor)) if header & 0x8000 else (predictor+32768)%65536-32768
                index = max(0, min(88, index+_CHANGES[nibble & 7]))
                out.extend(struct.pack('<h', predictor))
                if len(out)//2 >= limit:
                    return bytes(out)
    return bytes(out)


def preview(image, asset, selection):
    index = formats.integer(selection.get('sample', 0), 'Sample', 0, len(asset['samples'])-1)
    rate = formats.integer(selection.get('rate', 11025), 'Preview sample rate', 1000, 192000)
    sample = asset['samples'][index]
    at, size = sample['offset'], sample['size']
    if not 0 <= at < at+size <= len(image):
        raise formats.AssetError('The sound bank changed. Rescan ROM Explorer.')
    limit = min(size//20*32, rate*formats.MAX_SECONDS, (formats.MAX_BYTES-44)//2)
    pcm = decode(memoryview(image)[at:at+size], limit)
    payload, details = formats.pcm(pcm, dict(format='pcm-s16le', channels=1, rate=rate, length=len(pcm)))
    details.update(sample=index, note=asset['reason'])
    return dict(media='audio', mime='audio/wav', data_url='data:audio/wav;base64,'+base64.b64encode(payload).decode(),
                details=details, settings=dict(asset['preview_settings'], sample=index, rate=rate))
