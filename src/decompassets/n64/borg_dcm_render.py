"""Mix the original PCM voices for a single pass through a DCM sequence."""

import math
import sys
from array import array
from dataclasses import dataclass

from ..formats import MAX_SECONDS, AssetError

RATE = 22050


@dataclass
class _Voice:
    pitch: int = 0
    volume: int = 0
    pan: int = 128
    instrument: int | None = None
    position: float = 0
    tick: int = 0
    repeats: int = 0


def render(instruments, events, samples):
    duration = min(MAX_SECONDS*1000, events[-1].milliseconds+20 if events else 0)
    frames = duration*RATE//1000
    left, right = array('f', [0])*frames, array('f', [0])*frames
    voices = {}
    mixed = work = 0

    def advance(voice, tick):
        nonlocal work
        at = voice.tick*RATE//1000
        stop = min(frames, tick*RATE//1000)
        voice.tick = tick
        if voice.instrument is None or voice.pitch <= 0 or at >= stop:
            return
        index, loop_start, loop_end, _ = instruments[voice.instrument]
        pcm = samples[index]
        step = voice.pitch/RATE
        gain = voice.volume/255
        pan = voice.pan/255
        lgain, rgain = gain*math.sqrt(1-pan), gain*math.sqrt(pan)
        position = voice.position
        for frame in range(at, stop):
            if voice.repeats and loop_end > loop_start and position >= loop_end:
                count = int((position-loop_start)//(loop_end-loop_start))
                if voice.repeats != 255:
                    count = min(count, voice.repeats)
                    voice.repeats -= count
                position -= count*(loop_end-loop_start)
            source = int(position)
            if source >= len(pcm):
                voice.instrument = None
                break
            following = loop_start if voice.repeats and loop_end > loop_start and source+1 == loop_end else min(source+1, len(pcm)-1)
            value = pcm[source]+(pcm[following]-pcm[source])*(position-source)
            left[frame] += value*lgain
            right[frame] += value*rgain
            position += step
            work += 1
        if work > RATE*MAX_SECONDS*32:
            raise AssetError('The Borg sequence exceeds the mixing limit.')
        voice.position = position

    for event in events:
        tick = event.milliseconds
        if tick >= duration:
            break
        voice = voices.setdefault(event.channel, _Voice())
        advance(voice, tick)
        if event.pitch is not None:
            voice.pitch = event.pitch
        if event.volume is not None:
            voice.volume = event.volume
        if event.pan is not None:
            voice.pan = event.pan
        if event.stop:
            voice.instrument = None
        if event.start:
            voice.instrument = event.instrument
            voice.position = event.sample_offset
            voice.repeats = instruments[event.instrument][3]
            mixed += 1
    for voice in voices.values():
        advance(voice, duration)
    if not work:
        raise AssetError('This Borg sequence contains no playable samples in the preview window.')
    peak = max(32768, max(map(abs, left)), max(map(abs, right)))
    pcm = array('h', (round(value*32000/peak) for pair in zip(left, right) for value in pair))
    if sys.byteorder != 'little':
        pcm.byteswap()
    return pcm.tobytes(), dict(voice_starts=mixed, truncated=bool(events and events[-1].milliseconds+20>duration))
