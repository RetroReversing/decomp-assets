"""Adjacent bit-packed B1 sample banks followed by an S1 sequence directory."""

import itertools
import re

from ..formats import AssetError, integer
from . import audio, uv_sequences

BANK = 'lz-b1-bank'
SONGS = 'lz-b1-songs'
# Nine-bit literal tokens spelling the B1 header and single bank pointer prefix.
_PREFIX = re.compile(b'\xa1\x4c\x60\x10\x18\x04')
_LIMIT = 64 * 1024


def unpack(image, start):
    source = image[start:start + _LIMIT]
    cursor = work = available = 0

    def take(count):
        nonlocal cursor, work, available
        while available < count:
            if cursor == len(source):
                raise AssetError('Truncated audio control bitstream.')
            work = work << 8 | source[cursor]
            cursor += 1
            available += 8
        available -= count
        result = work >> available
        work &= (1 << available) - 1
        return result

    ring = bytearray(8192)
    mask = len(ring) - 1
    destination = 1
    output = bytearray()
    while len(output) < _LIMIT:
        if take(1):
            values = (take(8),)
        else:
            offset = take(13)
            if not offset:
                if work:
                    raise AssetError('Nonzero padding at the end of the audio control bitstream.')
                return bytes(output), start + cursor
            length = take(3) + 3
            # The source can overlap the output within the circular dictionary.
            values = (ring[(offset + i) & mask] for i in range(length))
        for value in values:
            output.append(value)
            ring[destination] = value
            destination = (destination + 1) & mask
    raise AssetError('Audio control bitstream exceeds its decoded size limit.')


def _bank(image, start, check):
    if not _PREFIX.match(image, start):
        return None
    try:
        controls, end = unpack(image, start)
        try:
            bank = audio.bank(controls, 0, check=check)
        except audio.KeyMapError:
            bank = audio.bank(controls, 0, sample_only=True, check=check)
    except (AssetError, audio.BankError):
        return None
    base = (end + 15) & ~15
    if not bank['samples'] or base >= len(image) or any(image[end:base]):
        return None
    if not audio._fits(image, bank, base, [audio.MAX_HEADER_CHECKS], check):
        return None
    last = uv_sequences._sample_end(bank['samples'], base)
    following = (last + 15) & ~15
    if any(image[last:following]):
        return None
    return controls, bank, base, following


def _asset(start, bank, base):
    return dict(offset=start, size=base-start, kind='audio', media='audio', audio_kind='sample bank',
                layout=BANK, label='Compressed B1 sample bank', confidence='validated',
                table_offset=base, samples=[{**sample, 'offset':base + sample['relative_offset']}
                                           for sample in bank['samples']],
                reason='The packed instrument graph and every sample frame validate against the adjacent wave table.',
                preview_settings=dict(format='auto', source='rom', offset=start))


def regions(image, *, check=lambda: None, progress=lambda _: None):
    found = []
    for marker in itertools.islice(_PREFIX.finditer(image), 128):
        check()
        start = marker.start()
        if start % 16 or not (music := _bank(image, start, check)):
            continue
        _, instruments, base, second = music
        if not instruments['programs'] or not (effects := _bank(image, second, check)):
            continue
        _, samples, sample_base, sequence_at = effects
        rows = uv_sequences._entries(image, sequence_at, len(image), check, exact=False)
        if not rows:
            continue
        found.extend((_asset(start, instruments, base), _asset(second, samples, sample_base)))
        end = (rows[-1]['offset'] + rows[-1]['size'] + 3) & ~3
        songs = uv_sequences._asset(sequence_at, end, rows, 'Compact MIDI music directory',
                                    'The S1 directory follows the two validated compressed B1 banks.', start)
        found.append({**songs, 'layout':SONGS, 'table_offset':base, 'effects_control':second})
    return found


def preview(image, asset, selection):
    start = asset['offset'] if asset['layout'] == BANK else asset['control']
    parsed = _bank(image, start, lambda: None)
    if parsed is None or parsed[2] != asset['table_offset']:
        raise AssetError('The compressed B1 bank changed. Rescan ROM Explorer.')
    controls, bank, base, following = parsed
    if asset['layout'] == BANK:
        return audio.preview(image, _asset(start, bank, base), selection, book_image=controls)
    if 'sample' not in selection:
        return uv_sequences.preview(image, asset, selection)
    effects = _bank(image, following, lambda: None)
    if following != asset['effects_control'] or effects is None or effects[3] != asset['offset']:
        raise AssetError('The S1 directory is no longer adjacent to the audio banks. Rescan ROM Explorer.')
    index = integer(selection['sample'], 'Sequence', 0, len(asset['sequences'])-1)
    return uv_sequences.render_sequence(image, asset, index, bank, base, book_image=controls)
