"""Consecutive self-bounded MORT speech clips."""
import re

from .. import formats
from . import b1_speech, mort

LAYOUT = 'contiguous-mort-speech'
_MAX_CLIP = 1024 * 1024
_MAX_CLIPS = 4096


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    consumed = 0
    for match in re.finditer(b'MORT', image):
        start = match.start()
        if start < consumed or start % 4:
            continue
        check()
        at = start
        clips = []
        while len(clips) < _MAX_CLIPS and at+mort.HEADER.size <= len(image):
            magic, frames, rate, words = mort.HEADER.unpack_from(image, at)
            size = words*4
            if (magic != b'MORT' or not frames or not 4000 <= rate <= 48000
                    or not mort.HEADER.size < size <= _MAX_CLIP or at+size > len(image)):
                break
            try:
                mort.decode(image[at:at+size], 1)
            except formats.AssetError:
                break
            clips.append(dict(offset=at, size=size, rate=rate, samples=frames*mort.SAMPLES_PER_FRAME,
                              codec='Factor 5 MORT', label=f'Clip {len(clips)+1}', preview_available=True))
            at += size
        if len(clips) >= 2:
            result.append(dict(offset=start, size=at-start, kind='audio', media='audio', layout=LAYOUT,
                               label='Consecutive speech clips', confidence='validated', audio_kind='speech',
                               sample_count=len(clips), samples=clips,
                               reason='Consecutive MORT headers bound each clip and its first frame decodes.',
                               preview_settings=dict(format='auto', source='rom', offset=start)))
            consumed = at
    return result


def preview(image, asset, selection):
    return b1_speech.preview(image, asset, selection)
