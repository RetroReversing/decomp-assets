"""Borg11 signed PCM sample previews."""

import base64
import struct

from .. import formats
from . import borg

_HEADER = struct.Struct('>4I')
_RATE = 44100


def sample(data):
    if len(data) < _HEADER.size:
        return None
    flags, size, frames, offset = _HEADER.unpack_from(data)
    if flags not in (0x14, 0x18):
        return None
    width = 1 if flags == 0x14 else 2
    if not frames or size != frames*width or not _HEADER.size <= offset <= len(data)-size:
        return None
    return offset, frames, width


def regions(image, rows, *, check=lambda: None, progress=lambda _: None):
    result = []
    for index, (kind, compression, stored, expanded, offset) in enumerate(rows):
        if kind != 11:
            continue
        check()
        try:
            data = borg.member(image, offset, stored, expanded, compression)
        except formats.AssetError:
            continue
        if info := sample(data):
            _, frames, width = info
            codec = f'Borg PCM{width*8}'
            result.append(dict(offset=offset, size=stored, kind='audio', media='audio', layout='borg-audio',
                               audio_kind='indexed sample directory', confidence='validated', label=f'Borg sample {index}',
                               expanded_size=expanded, compression=compression, borg_index=index,
                               samples=[dict(offset=offset, size=stored, rate=_RATE, samples=frames,
                                             codec=codec, preview_available=True)],
                               preview_settings=dict(format='auto', source='rom', offset=offset),
                               reason='The Borg archive and the PCM header agree on the sample extent. Preview uses the nominal rate.'))
    return result


def preview(image, asset, selection):
    data = borg.member(image, asset['offset'], asset['size'], asset['expanded_size'], asset['compression'])
    info = sample(data)
    if info is None:
        raise formats.AssetError('The Borg sample changed. Rescan ROM Explorer.')
    offset, frames, width = info
    count = min(frames, formats.MAX_SECONDS*_RATE, (formats.MAX_BYTES-44)//width)
    pcm = data[offset:offset+count*width]
    if width == 1:
        pcm = bytes(value ^ 128 for value in pcm)
    payload, details = formats.pcm(pcm, dict(format='pcm-u8' if width == 1 else 'pcm-s16be',
                                              rate=_RATE, length=len(pcm)))
    details.update(format=f'Borg PCM{width*8}', truncated=count<frames, original_samples=frames,
                   note='Mono sample at its nominal rate. Music and effects may change its pitch at runtime.')
    return dict(media='audio', mime='audio/wav', details=details,
                data_url='data:audio/wav;base64,'+base64.b64encode(payload).decode(),
                settings=asset['preview_settings'])
