"""Sample-backed effects from checked named file tables."""
from . import libmus_song, named_file_textures


def regions(image, banks, *, check=lambda: None):
    result = []
    for _, rows in named_file_textures.tables(image, check):
        by_name = {row[0]: row for row in rows}
        for name, kind, packed, size, _, start, _ in rows:
            if kind or not name.endswith('.BFX'):
                continue
            control = by_name.get(name[:-4]+'.PTR')
            candidates = [bank for bank in banks if control and bank['offset'] == control[5]
                          and bank.get('table_offset') is not None]
            if len(candidates) != 1:
                continue
            bank = candidates[0]
            waves = {sample['instrument'] for sample in bank['samples']}
            scores = libmus_song.binary_effects(image[start:start+packed], waves, allow_empty=True)
            if not scores:
                continue
            result.append(dict(offset=start, size=size, kind='audio sequence', media='audio',
                               audio_kind='indexed sample directory', control=bank['offset'],
                               table_offset=bank['table_offset'], sequence_packed=False, allow_empty=True,
                               layout='libmus-binary-effects', confidence='validated',
                               label=f'{name} · libmus effects',
                               samples=[dict(label=f'Effect {i}', codec='Nintendo libmus',
                                             preview_available=bool(score['notes']))
                                        for i, score in enumerate(scores)],
                               channels=1, notes=sum(len(score['notes']) for score in scores),
                               loops=sum(score['loops'] for score in scores),
                               reason='Named effects and pointer-bank files agree, and every track resolves to that bank.',
                               preview_settings=dict(format='auto', source='rom', offset=start)))
    return result
