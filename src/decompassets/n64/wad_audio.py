"""Sound banks whose control and sample tables are paired archive members."""

from collections import defaultdict

from .. import formats
from . import audio, lzhuf, wad_resources

LAYOUT = 'wad-sound-bank'


def _unpack(image, offset, stored, expanded, check=lambda: None):
    source = image[offset:offset+stored]
    if len(source) != stored:
        raise formats.AssetError('The archive member changed. Rescan ROM Explorer.')
    return lzhuf.unpack(source, expanded, check) if stored != expanded else source


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result, seen = [], set()
    for rows in wad_resources._groups(image, check):
        tables = defaultdict(set)
        for name, offset, _, size, decoded in rows:
            if name.endswith('.TBL'):
                tables[name[:-4]].add((offset,size,decoded))
        for name, offset, _, size, decoded in rows:
            if not name.endswith('.CTL') or len(tables[name[:-4]]) != 1:
                continue
            table, table_size, table_decoded = next(iter(tables[name[:-4]]))
            if (offset,table) in seen:
                continue
            seen.add((offset,table))
            try:
                control = _unpack(image, offset, size, decoded, check)
                bank = audio.bank(control, 0, check=check)
            except (formats.AssetError, audio.BankError):
                continue
            if not bank['samples'] or any(s['relative_offset'] + s['size'] > table_decoded for s in bank['samples']):
                continue
            samples = [dict(s, offset=s['relative_offset'], label=f'Sample {i+1}', preview_available=True)
                       for i,s in enumerate(bank['samples'])]
            result.append(dict(offset=offset, size=size, kind='audio', media='audio', layout=LAYOUT,
                               label=name[:-4] + ' sound bank', confidence='validated', audio_kind='N64 sample bank',
                               reason='Matching archive members provide bounded B1 controls and sample data.',
                               decoded_size=decoded, table_offset=table, table_size=table_size,
                               table_decoded_size=table_decoded, sample_count=len(samples), samples=samples,
                               preview_settings=dict(source='rom', format='auto', offset=offset)))
    return result


def preview(image, asset, selection):
    control = _unpack(image, asset['offset'], asset['size'], asset['decoded_size'])
    table = _unpack(image, asset['table_offset'], asset['table_size'], asset['table_decoded_size'])
    try:
        bank = audio.bank(control, 0)
    except audio.BankError as exc:
        raise formats.AssetError('The sound controls changed. Rescan ROM Explorer.') from exc
    samples = [dict(s, offset=s['relative_offset']) for s in bank['samples']]
    return audio.preview(table, {**asset, 'samples': samples}, selection, book_image=control)
