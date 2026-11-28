"""A sectioned archive's B1 bank with individually validated samples."""

import struct

from . import audio, indexed_be_textures


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for base, sections in indexed_be_textures.archives(image, check):
        index = base + sections[49]
        start, end = base + sections[50], base + sections[51]
        if index + 8 > base + sections[50] or start + 8 > end or image[start:start + 2] != b'B1':
            continue
        control_size, table_end = struct.unpack_from('>II', image, index)
        if not (8 <= control_size < table_end <= end - start):
            continue
        table = start + control_size
        try:
            info = audio.bank(image, start, control_end=table, sample_only=True, partial_samples=True, check=check)
        except audio.BankError:
            continue
        if (info['size'] > control_size or any(rel + size > table_end - control_size
                                                for rel, size in info['extents'])):
            continue
        info['corroborated'] = True
        if not audio._fits(image, info, table, [audio.MAX_HEADER_CHECKS], check):
            continue
        samples = [{**sample, 'offset': table + sample['relative_offset']} for sample in info['samples']]
        reason = ('A checked section directory bounds the B1 controls and sample table; each listed sample and '
                  'ADPCM frame selector passed. Unsupported samples and invalid loops are omitted. Static structure '
                  'does not prove runtime use. Preview uses the nominal rate without pitch, mixing or loops.')
        common = dict(media='audio', audio_kind='sample bank', table_confidence='validated', table_offset=table,
                      reason=reason)
        result.append(dict(offset=start, size=control_size, kind='audio', label='N64 sound-bank controls',
                           confidence='validated', samples=samples,
                           preview_settings=dict(format='auto', source='rom', offset=start), **common))
        seen = set()
        for sample in samples:
            key = sample['offset'], sample['size']
            if key in seen:
                continue
            seen.add(key)
            result.append(dict(offset=sample['offset'], size=sample['size'], kind='audio',
                               label=sample['codec'] + ' sample', confidence='validated', samples=[sample],
                               preview_settings=dict(format='auto', source='rom', offset=sample['offset']), **common))
    return result
