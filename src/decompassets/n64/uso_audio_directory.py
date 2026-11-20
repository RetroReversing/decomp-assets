"""Resolve named USO audio resources through their EAD loader tables."""

import re
import struct
from itertools import islice

from . import ead_sequence
from .resource_inspection import table

_HEADER = re.compile(rb'\0[\x08-\x80]\0{18}', re.S)
_ENTRY = struct.Struct('>II8B')
_HEADER_SIZE = 16


def _entries(image, at, payload_size, *, aliases):
    """Require real entries to tile the named payload, including its padding."""
    if not 0 <= at <= len(image)-_HEADER_SIZE:
        return None
    count = int.from_bytes(image[at:at+2], 'big')
    end = at+_HEADER_SIZE+count*_ENTRY.size
    if not 1 <= count <= 128 or any(image[at+2:at+_HEADER_SIZE]) or end > len(image):
        return None
    entries = list(_ENTRY.iter_unpack(image[at+_HEADER_SIZE:end]))
    cursor = 0
    for offset, size, medium, policy, *_ in entries:
        if medium != 2 or policy > 4:
            return None
        if size:
            if offset != cursor or size % 16 or cursor+size > payload_size:
                return None
            cursor += size
        elif not aliases or offset >= count or entries[offset][1] == 0:
            return None
    return (entries, end) if cursor == payload_size else None


def _fonts(image, at, end, count, font_count):
    if at+count*2 > end:
        return None
    cursor = at+count*2
    result = []
    for offset, in struct.iter_unpack('>H', image[at:cursor]):
        if at+offset != cursor or cursor >= end:
            return None
        size = image[cursor]
        cursor += 1
        if not 1 <= size <= 16 or cursor+size > end:
            return None
        fonts = list(image[cursor:cursor+size])
        if max(fonts) >= font_count:
            return None
        result.append(fonts)
        cursor += size
    if end-cursor >= 16 or any(image[cursor:end]):
        return None
    return result


def locate(image, control_size, sequence_size, wave_size, *, check=lambda: None):
    """Accept a unique set of complete sequence, font and sample-bank tables."""
    found = None
    for hit in islice(_HEADER.finditer(image), 16384):
        at = hit.start()
        if at%4:
            continue
        check()
        sequence = _entries(image, at, sequence_size, aliases=True)
        if not sequence:
            continue
        sequences, wave_at = sequence
        waves = _entries(image, wave_at, wave_size, aliases=False)
        if not waves:
            continue
        wave_rows, end = waves
        for candidate in _HEADER.finditer(image, max(0, at-16384), at):
            font_at = candidate.start()
            if font_at%4:
                continue
            fonts = _entries(image, font_at, control_size, aliases=True)
            if not fonts:
                continue
            font_rows, map_at = fonts
            if any(font[4] >= len(wave_rows) or font[5] != 255 and font[5] >= len(wave_rows) for font in font_rows):
                continue
            link = _fonts(image, map_at, at, len(sequences), len(font_rows))
            if link is None:
                continue
            if found is not None:
                return None
            found = dict(offset=font_at, end=end, sequences=sequences, fonts=font_rows,
                         waves=wave_rows, sequence_fonts=link, sequence_table=at)
    return found


def asset(directory, sequence_start):
    """Expose the loader's real sequence entries and aliases without guessing opcodes."""
    offset = directory['sequence_table']
    entries = []
    for index, ((start, size, *_), fonts) in enumerate(zip(directory['sequences'], directory['sequence_fonts'])):
        real_start, real_size, *_ = directory['sequences'][index if size else start]
        entries.append(dict(sequence=index, alias=None if size else start, offset=sequence_start+real_start,
                            bytes=real_size, fonts=fonts))
    return dict(offset=offset, size=_HEADER_SIZE+len(entries)*_ENTRY.size, label='USO sequence directory',
                kind='music sequence', media='metadata', layout='uso-sequence-directory', confidence='validated',
                sequences=entries, reason='The sequence, instrument and wave tables exactly cover the three USO payloads.',
                preview_settings=dict(format='auto', source='rom', offset=offset))


def preview(image, asset, selection):
    entries = asset['sequences']
    schedules = {}

    def entry(index):
        item = entries[index]
        start, size = item['offset'], item['bytes']
        key = (start, size)
        if key not in schedules:
            valid = 0 <= start < start+size <= len(image) and size <= 256 * 1024
            schedules[key] = ead_sequence.schedule(image[start:start+size]) if valid else None
        parsed = schedules[key]
        return {**item,
                'channels': len({start.channel for start in parsed['channels']}) if parsed else None,
                'channel_starts': len(parsed['channels']) if parsed else None,
                'root_ticks': parsed['ticks'] if parsed else None,
                'conditional': parsed['conditional'] if parsed else None}
    return dict(media='metadata', title=asset['label'], fields={'Sequencer': 'Nintendo EAD'},
                table=table(asset['label'], ['index', 'sequence', 'alias', 'offset', 'bytes', 'fonts',
                                       'channels', 'channel_starts', 'root_ticks', 'conditional'],
                            len(entries), entry, selection),
                settings=asset['preview_settings'])
