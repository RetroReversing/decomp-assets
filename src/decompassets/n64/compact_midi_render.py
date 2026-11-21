"""Mix a bounded, single-pass preview from the compact MIDI player's B1 bank."""

import math
import struct
import sys
from array import array
from bisect import bisect_right

from .. import formats
from . import audio

RATE = 22050
_FRAME_LIMIT = RATE * formats.MAX_SECONDS


def _clock(division, events):
    tempos = {0: 500000}
    for event in events:
        if event.status == 0xff:
            tempos[event.tick] = int.from_bytes(bytes(event.data), 'big')
    ticks, starts, rates = [], [], []
    for tick, tempo in sorted(tempos.items()):
        starts.append(starts[-1]+(tick-ticks[-1])*rates[-1] if ticks else 0)
        ticks.append(tick)
        rates.append(RATE*tempo/(division*1_000_000))

    def frame(tick):
        i = bisect_right(ticks, tick)-1
        return round(starts[i]+(tick-ticks[i])*rates[i])

    return frame


def _decode(image, base, sample):
    offset = base+sample['relative_offset']
    count = sample['samples']
    if sample['codec'] == 'N64 VADPCM':
        predictors = sample['predictors']
        book = struct.unpack_from(f'>{predictors*16}h', image, sample['book_offset'])
        encoded = image[offset:offset+sample['encoded_size']]
        data = audio.vadpcm(encoded, book, predictors, count)
        little = True
    else:
        data = image[offset:offset+sample['size']]
        little = False
    pcm = array('h')
    pcm.frombytes(data)
    if (sys.byteorder == 'little') != little:
        pcm.byteswap()
    return pcm


def render(image, base, division, events, voices, *, label='compact MIDI'):
    frame = _clock(division, events)
    notes = []
    end = 0
    for event, voice in voices:
        at, stop = frame(event.tick), frame(event.tick+event.duration)
        end = max(end, stop)
        if at < _FRAME_LIMIT:
            notes.append((at, stop, voice))
    frames = min(_FRAME_LIMIT, max((stop for _, stop, _ in notes), default=0))
    left, right = array('f', [0])*frames, array('f', [0])*frames
    cache = {}
    decoded = mixed = work = 0
    for at, stop, voice in notes:
        stop = min(stop, frames)
        if not voice or not voice['gain'] or at >= stop:
            continue
        sample = voice['sample']
        key = sample['relative_offset'], sample['size'], sample.get('book_offset')
        if key not in cache:
            decoded += sample['samples']
            if decoded > 4*1024*1024:
                raise formats.AssetError(f'The {label} preview exceeds the decoded sample limit.')
            cache[key] = _decode(image, base, sample)
        pcm = cache[key]
        step = sample['rate']/RATE * 2**(voice['pitch']/12)
        pan = voice['pan']/127
        gain = voice['gain']
        l_gain, r_gain = gain*math.sqrt(1-pan), gain*math.sqrt(pan)
        loop = sample.get('loop', {})
        loop_start, loop_end, repeats = (loop.get(key, 0) for key in ('start', 'end', 'count'))
        loop_length = loop_end-loop_start
        if not loop_length:
            repeats = 0
        position = 0.0
        for i in range(at, stop):
            if repeats and position >= loop_end:
                cycles = int((position-loop_start)//loop_length)
                crossed = min(repeats, cycles)
                position -= crossed*loop_length
                repeats -= crossed
            index = int(position)
            if index >= len(pcm):
                break
            following = loop_start if repeats and index+1 == loop_end else min(index+1, len(pcm)-1)
            value = pcm[index]+(pcm[following]-pcm[index])*(position-index)
            value *= min(1, (i-at+1)/32, (stop-i)/64)
            left[i] += value*l_gain
            right[i] += value*r_gain
            position += step
            work += 1
        if work > _FRAME_LIMIT*16:
            raise formats.AssetError(f'The {label} preview exceeds the mixing limit.')
        mixed += 1
    if not mixed:
        raise formats.AssetError(f'This {label} sequence has no playable notes in the preview window.')
    peak = max(32767, max(map(abs, left)), max(map(abs, right)))
    pcm = array('h', (round(value*32000/peak) for pair in zip(left, right) for value in pair))
    if sys.byteorder != 'little':
        pcm.byteswap()
    return pcm.tobytes(), dict(mixed_notes=mixed, skipped_notes=len(notes)-mixed, truncated=end>frames)
