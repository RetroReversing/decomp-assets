"""Render a single-pass preview using cartridge instruments and sample data."""

import math
import sys
from array import array

from ..formats import MAX_SECONDS, AssetError
from . import musyx, musyx_song, musyx_voices

RATE = 22050
_MAX_VOICES = 4096
_MAX_DECODED_SAMPLES = 4 * 1024 * 1024
_MAX_MIXED_FRAMES = RATE * MAX_SECONDS * 16


def _score(data, group, song, frame_limit):
    score = musyx_song.arrangement(data)
    if score is None:
        raise AssetError('The MusyX arrangement does not fit the stored song.')
    streams = [musyx_song.events(data, lo, hi) for lo, hi in score['streams']]
    if any(stream is None for stream in streams):
        raise AssetError('The MusyX song contains an unsupported event stream.')
    tick_frames = RATE * 60 / (384 * score['tempo'])
    notes = []
    for track in score['tracks']:
        channel = track['channel']
        program, volume, pan, _, _ = group['setups'][song][channel]
        pages = group['drums'] if channel == 9 else group['pages']
        modulation = 0
        expression = 127
        for clip in track['clips']:
            if clip['program'] != 255:
                program = clip['program']
            for event in streams[clip['region']]:
                start = int((clip['tick'] + event['tick']) * tick_frames)
                if start >= frame_limit:
                    break
                kind, key, value = event['kind'], event['key'], event['value']
                if kind == 'program':
                    program = key
                if kind == 'controller':
                    control = value & 127 if value & 128 else 130
                    if control == 1:
                        modulation = key
                    elif control == 7:
                        volume = key
                    elif control == 10:
                        pan = key
                    elif control == 11:
                        expression = key
                if kind == 'note' and value and event['duration']:
                    page = pages.get(program)
                    if page is None:
                        raise AssetError('The MusyX song selects an instrument outside its program table.')
                    duration = max(1, int(event['duration'] * tick_frames))
                    notes.append((start, duration, page['object_id'], key, value, modulation, volume*expression, pan))
                    if len(notes) > _MAX_VOICES:
                        raise AssetError('This MusyX preview exceeds the note limit.')
    return notes


def render(image, data, group, song, pool, samples):
    frame_limit = RATE * MAX_SECONDS
    notes = _score(data, group, song, frame_limit)
    frames = min(frame_limit, max((at + duration for at, duration, *_ in notes), default=0))
    if not frames:
        raise AssetError('The MusyX song contains no playable note events in the preview window.')
    left, right = array('f', [0]) * frames, array('f', [0]) * frames
    cache = {}
    total_samples = mixed = skipped = voices = mixed_frames = 0
    for at, duration, obj, key, velocity, modulation, volume, pan in notes:
        played = False
        for identifier, pitch, offset, layer_gain, layer_pan in musyx_voices.attacks(
                image, pool, obj, key, velocity, modulation):
            sample = samples.get(identifier)
            if not sample or not sample['preview_available'] or offset >= sample['samples']:
                continue
            voices += 1
            if voices > _MAX_VOICES:
                raise AssetError('This MusyX preview exceeds the voice limit.')
            if identifier not in cache:
                n = sample['samples']
                total_samples += n
                if total_samples > _MAX_DECODED_SAMPLES:
                    raise AssetError('This MusyX preview exceeds the decoded sample limit.')
                pcm = array('h')
                pcm.frombytes(musyx.decode(image, sample['offset'], n))
                if sys.byteorder != 'little':
                    pcm.byteswap()
                cache[identifier] = pcm
            pcm = cache[identifier]
            step = sample['rate'] / RATE * 2 ** ((pitch - sample['root_key']) / 12)
            gain = layer_gain * volume * velocity / 127**4
            stereo = max(0, min(127, pan + (layer_pan - 64 if layer_pan is not None else 0))) / 127
            amplitudes = (gain * math.sqrt(1 - stereo), gain * math.sqrt(stereo))
            loop_start, loop_end = sample['loop_start'], sample['loop_end']
            stop = min(at+duration, frames)
            mixed_frames += stop-at
            if mixed_frames > _MAX_MIXED_FRAMES:
                raise AssetError('This MusyX preview exceeds the mixing limit.')
            position = offset
            for i in range(at, stop):
                if loop_end and position >= loop_end:
                    position = loop_start + (position - loop_start) % (loop_end - loop_start)
                idx = int(position)
                if idx >= len(pcm):
                    break
                following = loop_start if loop_end and idx+1 == loop_end else min(idx+1, len(pcm)-1)
                value = pcm[idx] + (pcm[following]-pcm[idx]) * (position-idx)
                fade = min(1, (at+duration-i)/64)
                left[i] += value * amplitudes[0] * fade
                right[i] += value * amplitudes[1] * fade
                position += step
            played = True
        mixed += played
        skipped += not played
    if not mixed:
        raise AssetError('The MusyX preview could not resolve any playable instrument samples.')
    peak = max(32767, max(map(abs, left)), max(map(abs, right)))
    pcm = array('h', (round(value * 32000 / peak) for pair in zip(left, right) for value in pair))
    if sys.byteorder != 'little':
        pcm.byteswap()
    return pcm.tobytes(), dict(mixed_notes=mixed, skipped_notes=skipped, truncated=frames == frame_limit)
