"""Sample-backed libmus songs in compressed big-endian IWAD members."""
from . import be_iwad_images, libmus_song, ptr_audio_v1


def regions(image, *, check=lambda: None, progress=lambda _: None):
    archives = list(be_iwad_images.archives(image, check))
    if not archives:
        return []
    banks = ptr_audio_v1.regions(image, check=check)
    if len(banks) != 1:
        return []
    bank = banks[0]
    waves = {sample['instrument'] for sample in bank['samples']}
    result = []
    for base, rows in archives:
        for index, (offset, size, name) in enumerate(rows):
            if size < 5:
                continue
            check()
            header = be_iwad_images.unpack(image, base, rows[index], prefix=16, check=check)
            if not header or header[:8] != b'\0\0\0\x10\0\0\0\x50':
                continue
            raw = be_iwad_images.unpack(image, base, rows[index], check=check)
            score = libmus_song.v1_song(raw, waves) if raw else None
            if not score:
                continue
            result.append(dict(offset=base+offset, size=size, kind='music sequence', media='audio',
                               audio_kind='indexed sample directory', control=bank['offset'], control_version=1,
                               table_offset=bank['table_offset'], directory=base, member=index,
                               sequence_codec='be-iwad', layout='libmus-raw-song', confidence='validated',
                               label=f'{name} · libmus song', channels=score['channels'],
                               notes=len(score['notes']), loops=score['loops'],
                               samples=[dict(label='Song', codec='Nintendo libmus', preview_available=True)],
                               reason='The decoded channel commands resolve to the unique validated wave bank.',
                               preview_settings=dict(format='auto', source='rom', offset=base+offset)))
    return result
