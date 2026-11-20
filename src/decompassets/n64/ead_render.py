"""Render a bounded stereo preview of a Nintendo EAD sequence."""

import math
import struct
import sys
from array import array
from bisect import bisect_right

from .. import formats
from . import audio

RATE = 22050
_TICKS_PER_BEAT = 48
_FRAME_LIMIT = RATE * formats.MAX_SECONDS


def _clock(tempos):
    changes = sorted(dict(tempos).items())
    ticks, starts, rates = [], [], []
    for tick, bpm in changes:
        starts.append(starts[-1]+(tick-ticks[-1])*rates[-1] if ticks else 0)
        ticks.append(tick)
        rates.append(RATE*60/(_TICKS_PER_BEAT*bpm))

    def frame(tick):
        i = bisect_right(ticks, tick)-1
        return round(starts[i]+(tick-ticks[i])*rates[i])

    return frame


def render(image, score, voices):
    frame = _clock(score['tempos'])
    notes = [note for note in score['notes'] if frame(note.tick) < _FRAME_LIMIT]
    end = max((frame(note.tick+note.duration) for note in notes), default=0)
    frames = min(_FRAME_LIMIT, end)
    left, right = array('f', [0])*frames, array('f', [0])*frames
    cache = {}
    decoded = mixed = work = 0
    for note, voice, sample, font, base in voices:
        at = frame(note.tick)
        stop = min(frames, frame(note.tick+note.duration))
        if at >= stop or not note.velocity or not note.volume:
            continue
        start = base+sample.offset
        key = start, sample, font
        if key not in cache:
            count = sample.encoded_size//sample.frame_size*16
            decoded += count
            if decoded > 4*1024*1024:
                raise formats.AssetError('The EAD preview exceeds the decoded sample limit.')
            book = struct.unpack_from(f'>{sample.predictors*16}h', font, sample.book)
            data = audio.vadpcm(image[start:start+sample.encoded_size], book, sample.predictors,
                                count, bits=(sample.frame_size-1)//2)
            pcm = array('h')
            pcm.frombytes(data)
            if sys.byteorder != 'little':
                pcm.byteswap()
            cache[key] = pcm
        pcm = cache[key]
        pitch = 2**((note.key-39)/12) if note.program < 126 else 1
        step = voice.tuning*pitch*32000/RATE
        pan = max(0, min(127, note.pan if voice.pan is None else voice.pan))/127
        gain = (min(127, note.volume)*note.velocity/127**2)**2
        l_gain, r_gain = gain*math.sqrt(1-pan), gain*math.sqrt(pan)
        loop_start, loop_end = sample.loop
        if not loop_end:
            stop = at+min(stop-at, math.ceil(len(pcm)/max(step, 1e-12)))
        work += stop-at
        if work > _FRAME_LIMIT*16:
            raise formats.AssetError('The EAD preview exceeds the mixing limit.')
        position = 0.0
        for i in range(at, stop):
            if loop_end and position >= loop_end:
                position = loop_start+(position-loop_start)%(loop_end-loop_start)
            index = int(position)
            if index >= len(pcm):
                break
            following = loop_start if loop_end and index+1 == loop_end else min(index+1, len(pcm)-1)
            value = pcm[index]+(pcm[following]-pcm[index])*(position-index)
            value *= min(1, (i-at+1)/32, (stop-i)/64)
            left[i] += value*l_gain
            right[i] += value*r_gain
            position += step
        mixed += 1
    if not mixed:
        raise formats.AssetError('This EAD sequence has no playable notes in the preview window.')
    peak = max(32767, max(map(abs, left)), max(map(abs, right)))
    pcm = array('h', (round(value*32000/peak) for pair in zip(left, right) for value in pair))
    if sys.byteorder != 'little':
        pcm.byteswap()
    return pcm.tobytes(), dict(mixed_notes=mixed, unplayed_notes=len(notes)-mixed, truncated=end > frames)
