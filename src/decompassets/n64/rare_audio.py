"""Fixed-record ADPCM banks with inline envelopes, loops and predictor books."""

import itertools
import re
import struct

from . import audio

INSTRUMENT = 18
VOICE = 216


def bank(image, start, check):
    instruments, flags, pad, rate = struct.unpack_from('>4H', image, start)
    if not 16 <= instruments <= 256 or flags or pad or rate != 22050:
        return None
    voices = (start+8+instruments*INSTRUMENT+3)&~3
    if voices > len(image):
        return None
    slots = set()
    for at in range(start+8, start+8+instruments*INSTRUMENT, INSTRUMENT):
        count, first = struct.unpack_from('>HH', image, at+14)
        if count and first+count > audio.MAX_SAMPLES:
            return None
        slots.update(range(first, first+count))
    if len(slots) < 32 or max(slots)+1 != len(slots):
        return None
    controls_end = voices+len(slots)*VOICE
    table = (controls_end+15)&~15
    if table >= len(image) or any(image[controls_end:table]):
        return None
    samples = {}
    for index in range(len(slots)):
        check()
        at = voices+index*VOICE
        relative, size, loop_start, loop_end, loop_count = struct.unpack_from('>5I', image, at+24)
        frames, padding = divmod(size,9)
        if (relative%2 or not frames or size > audio.MAX_BYTES or padding > 1
                or padding and size%2 or not loop_start <= loop_end <= frames*16
                or table+relative+size > len(image)):
            return None
        sample = dict(relative_offset=relative,offset=table+relative,size=size,encoded_size=frames*9,
                      samples=frames*16,rate=rate,codec='N64 VADPCM',book_offset=at+80,predictors=4)
        if loop_end:
            sample['loop'] = dict(start=loop_start,end=loop_end,count=loop_count)
        samples.setdefault((relative,size), sample)
    if min(relative for relative,_ in samples) != 0:
        return None
    info = dict(offset=start,size=controls_end-start,samples=list(samples.values()))
    if not audio._fits(image,info,table,[audio.MAX_HEADER_CHECKS],check):
        return None
    return dict(**info,kind='audio',media='audio',audio_kind='sample bank',layout='rare-inline-adpcm',
                label='N64 inline ADPCM bank',confidence='validated',table_offset=table,
                reason='Contiguous voice indices, inline predictor books and every adjacent ADPCM frame validate.',
                preview_settings=dict(format='auto',source='rom',offset=start))


def regions(image, *, check=lambda: None, progress=lambda _: None):
    results = []
    # The storage has no magic. The nominal rate and zero header fields only
    # select candidates; the complete graph and sample table establish the match.
    for hit in itertools.islice(re.finditer(rb'(?=\x00[\x10-\xff]\x00{4}\x56\x22)',image),4096):
        check()
        start = hit.start()
        if start%16 == 0 and (asset := bank(image,start,check)):
            results.append(asset)
    return results
