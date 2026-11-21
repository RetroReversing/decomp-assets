"""Identify DEAN audio in byte-sum resource directories."""

import base64
import re
import struct

from ..formats import AssetError, integer, pcm
from . import dean_codec

ROW = struct.Struct('>III')
RAW_HEADER = re.compile(rb'RAW!....\x00\x00\x2b\x11', re.S)
MAX_ROWS = 2048
MAX_ENTRY = 4 * 1024 * 1024


def _entry(image, offset, size):
    if not 12 < size <= MAX_ENTRY or not 0 <= offset <= len(image) - 20:
        return None
    if image[offset:offset + 4] != b'RAW!' or struct.unpack_from('>I', image, offset + 4)[0] != size:
        return None
    end = offset + 8 + size
    trailer = (end + 3) & ~3
    if trailer + 4 > len(image) or any(image[end:trailer]) or image[trailer:trailer + 4] != b'END!':
        return None
    rate, frames, payload = ROW.unpack_from(image, offset + 8)
    if rate != 11025 or frames == 0 or payload != size - 12:
        return None
    return trailer + 4, rate, frames, payload


def _directory(image, root, check):
    size = struct.unpack_from('>I', image, root)[0]
    if size % ROW.size or not 2 <= size // ROW.size <= MAX_ROWS or root + size > len(image):
        return []
    assets = []
    expected = root + size
    for index, (relative, length, checksum) in enumerate(ROW.iter_unpack(image[root:root + size])):
        check()
        offset = root + relative
        if offset != expected or not (entry := _entry(image, offset, length)):
            return []
        if sum(image[offset + 8:offset + 8 + length]) != checksum:
            return []
        expected, rate, frames, payload = entry
        sample = dict(offset=offset + 20, size=payload, codec='Acclaim DEAN', rate=rate, samples=None,
                      label=str(index + 1), preview_available=False)
        assets.append(dict(offset=offset, size=expected - offset, kind='audio', media='audio', confidence='validated',
                           label='DEAN audio', audio_kind='dean stream', samples=[sample],
                           table_confidence='Verified resource directory', table_offset=root,
                           reason='DEAN stream header, directory length and byte sum agree.',
                           preview_settings=dict(format='auto', source='rom', offset=offset)))
    return assets


def regions(image, *, check=lambda: None, progress=lambda _: None):
    assets = []
    covered = 0
    for index, match in enumerate(RAW_HEADER.finditer(image)):
        check()
        offset = match.start()
        if offset % 4 or offset < covered:
            continue
        if index >= 4096:
            break
        # The first relative offset doubles as the directory's length.
        for size in range(2 * ROW.size, min(offset, MAX_ROWS * ROW.size) + 1, ROW.size):
            root = offset - size
            if struct.unpack_from('>I', image, root)[0] != size:
                continue
            if found := _directory(image, root, check):
                assets.extend(found)
                covered = found[-1]['offset'] + found[-1]['size']
                progress(dict(phase='Checking DEAN audio directories', done=covered, total=len(image)))
                break
    if assets and (book := dean_codec.table_offset(image)) is not None:
        for asset in assets:
            _, frames, _ = ROW.unpack_from(image, asset['offset'] + 8)
            if frames > 1:
                asset['dean_codebooks'] = book
                asset['samples'][0].update(samples=(frames - 1) * dean_codec.BLOCK_SAMPLES, preview_available=True)
    return assets


def preview(image, asset, selection):
    integer(selection.get('sample', 0), 'Sample', 0, 0)
    offset = asset['offset']
    if not 0 <= offset <= len(image) - 8:
        raise AssetError('The DEAN stream offset changed. Rescan ROM Explorer.')
    length = struct.unpack_from('>I', image, offset + 4)[0]
    entry = _entry(image, offset, length)
    if entry is None:
        raise AssetError('The DEAN stream header changed. Rescan ROM Explorer.')
    _, rate, frames, size = entry
    settings = dict(format='auto', source='rom', offset=offset, sample=0)
    if 'dean_codebooks' not in asset:
        return dict(media='metadata', title='Acclaim DEAN audio',
                    fields={'Sample rate (Hz)': rate, 'Encoded bytes': size, 'Playback': 'Codebooks unavailable'},
                    settings=settings)

    return render_clip(image, asset['dean_codebooks'], image[offset+20:offset+20+size], rate, frames, settings)


def render_clip(image, codebooks, payload, rate, frames, settings):
    count = min(frames-1, dean_codec.MAX_BLOCKS, rate*30//dean_codec.BLOCK_SAMPLES)
    raw = dean_codec.decode(image, codebooks, payload, count)
    wav, details = pcm(raw, dict(format='pcm-s16le', channels=1, rate=rate, length=len(raw)))
    details.pop('note')
    details['format'] = 'Acclaim DEAN'
    if count < frames - 1:
        details['preview'] = 'First 30 seconds'
    return dict(media='audio', mime='audio/wav', details=details, settings=settings,
                data_url='data:audio/wav;base64,' + base64.b64encode(wav).decode('ascii'))
