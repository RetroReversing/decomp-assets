"""Partial order-2 sample banks with compressed controls and independently checked wave padding."""
import re

from .. import formats, rnc
from . import audio

LAYOUT = 'rnc-control-samples'
_MAGIC = re.compile(b'RNC[\x01\x02]')
_LIMIT = 1024 * 1024
_ZERO = bytes(6)


def _control(image, offset, check):
    try:
        data, packed = rnc.unpack_at(image, offset, max_output=_LIMIT, max_packed=_LIMIT)
        if data[:2] != b'B1':return None
        info = audio.bank(data, 0, sample_only=True, partial_samples=True, check=check)
    except (rnc.RncError, audio.BankError):
        return None
    return data, packed, info


def _wave_table(image, end, info, check):
    extents = info['extents']
    if len(extents) < 64 or extents[0][0] != 0 or any(start % 8 for start, _ in extents):return None
    gaps = []
    for (at, size), (nxt, _) in zip(extents, extents[1:]):
        gap = nxt-at-size
        if gap != (-(at+size) % 8):return None
        if gap:gaps.append((at+size, gap))
    span = max(at+size for at, size in extents)
    probes = [at for at, size in gaps if size == 6]
    if len(probes) < 12 or span > len(image):return None
    probes = [probes[i*len(probes)//12] for i in range(12)]
    matches = []
    for base in range((end+7)&~7, len(image)-span+1, 8):
        if not base & 0xffff:check()
        if not all(image[base+p:base+p+6] == _ZERO for p in probes):continue
        if any(any(image[base+p:base+p+size]) for p,size in gaps):continue
        candidate = dict(offset=0, size=0, samples=info['samples'])
        if audio._fits(image, candidate, base, [audio.MAX_HEADER_CHECKS], check):
            matches.append(base)
            if len(matches)>1:return None
    return matches[0] if matches else None


def regions(image, *, check=lambda: None, **kwargs):
    result = []
    for hit in _MAGIC.finditer(image):
        check()
        at = hit.start()
        control = _control(image, at, check)
        if control is None:continue
        _, packed, info = control
        wave = _wave_table(image, at+packed, info, check)
        if wave is None:continue
        samples = [dict(sample, offset=wave+sample['relative_offset']) for sample in info['samples']]
        supported = {(sample['relative_offset'], sample['size']) for sample in samples}
        reason = ('A checksum-verified compressed control bank and unique zero-padded wave table agree on every '
                  'supported ADPCM frame. Other samples need further validation.')
        result.append(dict(offset=at, size=packed, kind='audio', media='audio', audio_kind='sample bank',
                           layout=LAYOUT, label='Compressed control sample bank', confidence='validated',
                           reason=reason, samples=samples, table_offset=wave, control_size=packed,
                           unsupported_samples=len(set(info['extents'])-supported),
                           preview_settings=dict(format='auto', source='rom', offset=at)))
    return result


def preview(image, asset, selection):
    control = _control(image, asset['offset'], lambda: None)
    if control is None or control[1] != asset['control_size']:
        raise formats.AssetError('The compressed sample bank changed. Rescan ROM Explorer.')
    return audio.preview(image, asset, selection, book_image=control[0])
