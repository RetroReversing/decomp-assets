"""Audio in sequential sized-file archives with independently checked B1 controls."""
import re
import struct

from . import audio

_ANCHOR = re.compile(rb'~audio~\\music\.ctl\x00', re.I)
_NAME = re.compile(rb'[!-~]{1,120}\x00')
_MAX_DIRECTORY = 128 * 1024
_MAX_FILES = 1024


def _directory(image, start, anchor):
    cursor = start
    entries = []
    for _ in range(_MAX_FILES):
        if cursor + 4 > len(image):
            return None
        size = int.from_bytes(image[cursor:cursor + 4], 'big')
        if size == 0xffffffff:
            cursor += 4
            break
        if not 0 < size <= len(image):
            return None
        name = _NAME.match(image, cursor + 4, min(len(image), cursor + 125))
        if name is None:
            return None
        entries.append((name[0][:-1].lower().replace(b'\\', b'/'), size))
        cursor = name.end()
        if cursor > anchor + _MAX_DIRECTORY:
            return None
    else:
        return None
    if len(entries) < 4:
        return None
    spans = {}
    for name, size in entries:
        if name in spans or cursor + size > len(image):
            return None
        spans[name] = (cursor, cursor + size)
        cursor += size
    if b'~audio~/music.ctl' not in spans or b'~audio~/music.tbl' not in spans:
        return None
    return len(entries), spans


def directories(image, *, check=lambda: None):
    for hit in _ANCHOR.finditer(image):
        check()
        candidates = []
        for start in range(max(0, hit.start() - _MAX_DIRECTORY + 3) & ~3, hit.start(), 4):
            if image[start + 4:start + 5] not in b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_~':
                continue
            parsed = _directory(image, start, hit.start())
            if parsed:
                candidates.append((start, *parsed))
        if candidates:
            # Suffixes of a valid directory also parse. The longest includes its
            # prefix; independent equal-length candidates remain ambiguous.
            candidates.sort(key=lambda row: row[1], reverse=True)
            if len(candidates) == 1 or candidates[0][1] > candidates[1][1]:
                yield candidates[0][2]


def regions(image, *, check=lambda: None, progress=lambda _: None):
    result = []
    for directory in directories(image, check=check):
        start, end = directory[b'~audio~/music.ctl']
        wave, wave_end = directory[b'~audio~/music.tbl']
        if end - start < 20 or int.from_bytes(image[start:start + 4], 'big') != 2:
            continue
        _, first, zero, second, _ = struct.unpack_from('>5I', image, start)
        middle = second - first + 20
        if zero or first < 20 or not 28 <= middle < end - start or middle % 4:
            continue
        for offset, relocation, limit in ((start + 20, first, start + middle),
                                          (start + middle, second, end)):
            try:
                bank = audio.bank(image, offset, relocation_base=relocation, control_end=limit,
                                  sample_only=True, partial_samples=True, check=check)
            except audio.BankError:
                continue
            if (any(relative + size > wave_end - wave for relative, size in bank['extents'])
                    or not audio._fits(image, bank, wave, [audio.MAX_HEADER_CHECKS], check)):
                continue
            samples = [dict(sample, offset=wave + sample['relative_offset']) for sample in bank['samples']]
            result.append(dict(offset=offset, size=bank['size'], label='Archive audio samples', kind='audio',
                               media='audio', audio_kind='sample bank', confidence='validated', samples=samples,
                               table_offset=wave, table_confidence='validated',
                               reason='Named archive members, relocated control pointers, bounded sample extents and ADPCM frame selectors agree. Unsupported codecs are omitted.',
                               preview_settings=dict(format='auto', source='rom', offset=offset)))
    return result
