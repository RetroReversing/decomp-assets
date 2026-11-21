"""VOX sound records held in BOLT archives."""

import struct

from .. import formats

VOX = 'bolt-vox'
STEP = (16,17,19,21,23,25,28,31,34,37,41,45,50,55,60,66,73,80,88,
        97,107,118,130,143,157,173,190,209,230,253,279,307,337,371,408,449,
        494,544,598,658,724,796,876,963,1060,1166,1282,1411,1552)
ADJUST = (-1,-1,-1,-1,2,4,6,8)


def voice(data):
    if len(data) < 14:
        return None
    flags, rate, size, reserved = struct.unpack_from('>HHII',data)
    if flags not in (0x0010,0x0210) or rate != 16384 or size != len(data)-12 or reserved:
        return None
    return dict(codec='Dialogic ADPCM',rate=rate,samples=size*2,size=size)


def pcm(data, limit):
    index = sample = 0
    result = bytearray()
    for byte in data[:limit]:
        for nibble in (byte>>4,byte&15):
            magnitude = nibble&7
            delta = ((2*magnitude+1)*STEP[index])>>3
            sample = max(-2048,min(2047,sample-delta if nibble&8 else sample+delta))
            index = max(0,min(48,index+ADJUST[magnitude]))
            result.extend(struct.pack('<h',sample*16))
    return result


def preview(data, asset):
    info = voice(data)
    if info is None:
        raise formats.AssetError('The BOLT voice header changed. Scan the ROM again.')
    limit = min(info['size'],info['rate']*formats.MAX_SECONDS//2,formats.MAX_BYTES//4)
    audio = pcm(data[12:],limit)
    result = formats.preview(audio,dict(format='pcm-s16le',rate=info['rate'],length=len(audio)))
    result['details'].update(format=info['codec'],note=asset['reason'],truncated=limit<info['size'])
    return result
