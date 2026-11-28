"""Recover B1 sample-table addresses from relocated control graphs in captured RAM."""
import itertools
import struct
from collections import Counter

from . import audio


def _anchors(image, info):
    """Distinct, discriminating predictor bytes and sample descriptors from a checked graph."""
    start, end = info['offset'], info['offset'] + info['size']
    books, waves, seen = [], [], set()
    for sample in info['samples']:
        book = sample.get('book_offset')
        if book is not None and len(books) < 8:
            signature = image[book:book+32]
            if (len(signature) == 32 and len(set(signature)) >= 8
                    and image.find(signature, start, end) == book
                    and image.find(signature, book+1, end) < 0):
                books.append((book-start, signature))
        pair = sample['relative_offset'], sample['size']
        if pair in seen or len(waves) >= 32:
            continue
        seen.add(pair)
        pattern = struct.pack('>II', *pair)
        position = image.find(pattern, start, end)
        if (position >= 0 and image.find(pattern, position+1, end) < 0
                and image[position+8] in (0, 1) and image[position+9] == 0):
            waves.append((position-start, pair[0], pair[1], image[position+8]))
    return books, waves


def tables(image, snapshots, *, check=lambda: None):
    """Require an identifiable control copy and matching relocations in two snapshots."""
    if len(snapshots) < 2:
        return {}
    resolved = {}
    for offset, relocated in itertools.islice(audio._candidates(image), audio.MAX_CANDIDATES):
        check()
        if relocated:
            continue
        try:
            info = audio.bank(image, offset, check=check)
        except audio.BankError:
            continue
        books, waves = _anchors(image, info)
        if not books or len(waves) < 2:
            continue
        observations = []
        for ram in snapshots:
            check()
            placements = Counter()
            for relative, signature in books:
                pos = ram.find(signature)
                if pos >= relative and ram.find(signature, pos+1) < 0:
                    placements[pos-relative] += 1
            if not placements:
                continue
            maximum = max(placements.values())
            candidates = [at for at, votes in placements.items() if votes == maximum]
            if len(candidates) != 1:
                continue
            at = candidates[0]
            if ram[at:at+4] != image[offset:offset+4] or at + info['size'] > len(ram):
                continue
            bases = Counter()
            for relative, original, length, codec in waves:
                value, ram_length = struct.unpack_from('>II', ram, at+relative)
                if ram_length == length and ram[at+relative+8:at+relative+10] == bytes((codec, 1)) and value >= original:
                    bases[value-original] += 1
            valid = [base for base, votes in bases.items() if votes >= 2]
            if len(valid) == 1:
                observations.append(valid[0])
        if len(observations) < 2 or len(set(observations)) != 1:
            continue
        base = observations[0]
        info['corroborated'] = True
        if audio._fits(image, info, base, [audio.MAX_HEADER_CHECKS], check):
            resolved[offset] = (base, info)
    return resolved


def regions(image, snapshots, *, check=lambda: None):
    found = []
    for offset, (base, info) in tables(image, snapshots, check=check).items():
        reason = ('A relocated B1 control graph in repeated RAM snapshots gives a consistent cartridge sample-table '
                  'base, and every ADPCM frame selector passed. Pitch, mixing and loop playback are separate.')
        samples = [{**sample, 'offset': base+sample['relative_offset']} for sample in info['samples']]
        common = dict(media='audio', audio_kind='sample bank', table_confidence='runtime relocated controls',
                      table_offset=base, bank_offset=offset, reason=reason)
        found.append(dict(offset=offset, size=info['size'], kind='audio', label='N64 sound-bank controls',
                          confidence='validated', preview_settings=dict(format='auto', source='rom', offset=offset),
                          samples=samples, **common))
        seen = set()
        for sample in samples:
            key = sample['offset'], sample['size']
            if key in seen:
                continue
            seen.add(key)
            found.append(dict(offset=key[0], size=key[1], kind='audio', label=sample['codec']+' sample',
                              confidence='validated', preview_settings=dict(format='auto', source='rom', offset=key[0]),
                              samples=[sample], **common))
    return found
