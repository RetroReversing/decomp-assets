"""MORT clips in directories following validated B1 sound controls."""
import base64

from .. import formats
from . import audio, mort

LAYOUT = 'b1-directory-speech'


def regions(image, *, check=lambda: None, **kwargs):
    found = []
    for offset, relocated in audio._candidates(image):
        check()
        if relocated:
            continue
        try:
            info = audio.bank(image, offset, check=check)
        except audio.BankError:
            continue
        directory = audio._following_sample_directory(image, info)
        if directory is None:
            continue
        at, base, offsets = directory
        clips = []
        for start, end in zip(offsets, offsets[1:]):
            start += base
            end += base
            if image[start:start+4] != b'MORT' or end-start < mort.HEADER.size:
                continue
            _, frames, rate, words = mort.HEADER.unpack_from(image, start)
            if frames and 4000 <= rate <= 48000 and words*4 == end-start:
                clips.append(dict(offset=start, size=end-start, rate=rate, samples=frames*mort.SAMPLES_PER_FRAME,
                                  codec='Factor 5 MORT', label=f'Clip {len(clips)+1}', preview_available=True))
        if clips:
            found.append(dict(offset=at, size=base-at, kind='audio', media='audio', layout=LAYOUT,
                              label='Indexed speech clips', confidence='validated', audio_kind='speech',
                              sample_count=len(clips), samples=clips,
                              reason='The sound directory bounds each MORT header and encoded clip.',
                              preview_settings=dict(format='auto', source='rom', offset=at)))
    return found


def preview(image, asset, selection):
    index = formats.integer(selection.get('sample', 0), 'Clip', 0, len(asset['samples'])-1)
    sample = asset['samples'][index]
    start, size, rate = sample['offset'], sample['size'], sample['rate']
    if not 0 <= start < start+size <= len(image):
        raise formats.AssetError('The speech clip changed. Rescan ROM Explorer.')
    frames = min(sample['samples']//mort.SAMPLES_PER_FRAME, rate*formats.MAX_SECONDS//mort.SAMPLES_PER_FRAME)
    pcm = mort.decode(image[start:start+size], frames)
    wav, details = formats.pcm(pcm, dict(format='pcm-s16le', rate=rate, length=len(pcm)))
    details.update(format=sample['codec'], sample=index, original_samples=sample['samples'],
                   truncated=len(pcm)//2 < sample['samples'], note=asset['reason'])
    return dict(media='audio', mime='audio/wav', data_url='data:audio/wav;base64,'+base64.b64encode(wav).decode(),
                details=details, settings=dict(asset['preview_settings'], sample=index))
