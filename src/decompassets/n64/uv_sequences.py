"""Validate UVMS music directories and their compact MIDI sequences."""

import re
import struct
from itertools import islice

from . import compact_midi

_ENTRY = struct.Struct('>II')


def directories(image, *, check=lambda: None):
    for match in islice(re.finditer(rb'FORM.{4}UVMS', image, re.S), 128):
        offset = match.start()
        end = offset+8+int.from_bytes(image[offset+4:offset+8], 'big')
        if offset%4 or not offset+12 <= end <= len(image):
            continue
        at = offset+12
        for _ in range(16):
            if at+8 > end:
                break
            tag, size = struct.unpack_from('>4sI', image, at)
            start = at+8
            at = start+size
            if at > end:
                break
            if tag == b'PAD ':
                continue
            if tag == b'SEQS' and at == end:
                rows = _entries(image, start, end, check)
                if rows:
                    yield offset, end, rows
            break


def _entries(image, start, end, check):
    if end-start < 4 or image[start:start+2] != b'S1':
        return None
    count = int.from_bytes(image[start+2:start+4], 'big')
    cursor = 4+count*_ENTRY.size
    if not 1 <= count <= 128 or cursor > end-start:
        return None
    rows = []
    for i in range(count):
        check()
        offset, length = _ENTRY.unpack_from(image, start+4+i*_ENTRY.size)
        first, last = start+offset, start+offset+length
        if offset != cursor or not 0 < length <= 256*1024 or last > end:
            return None
        score = compact_midi.sequence(image[first:last])
        if score is None:
            return None
        division, events = score
        notes = sum(event.status & 0xf0 == 0x90 and event.duration > 0 and event.data[1] > 0 for event in events)
        rows.append(dict(offset=first, size=length, division=division, notes=notes))
        cursor = (offset+length+3)&~3
    return rows if 0 <= end-start-cursor < 16 and not any(image[start+cursor:end]) else None


def regions(image, *, check=lambda: None, progress=lambda _: None):
    return [dict(offset=offset, size=end-offset, label='UV music directory', kind='music sequence',
                 media='metadata', layout='uv-sequence-directory', confidence='validated', sequences=rows,
                 reason='The indexed sequences fit the named ROM chunk and decode as compact MIDI.',
                 preview_settings=dict(format='auto', source='rom', offset=offset))
            for offset, end, rows in directories(image, check=check)]


def preview(image, asset, selection):
    from .resource_inspection import table

    rows = asset['sequences']
    return dict(media='metadata', title=asset['label'], fields={'Sequencer': 'Nintendo compact MIDI'},
                table=table(asset['label'], ['index', 'offset', 'size', 'division', 'notes'], len(rows),
                            lambda i: dict(index=i, **rows[i]), selection),
                settings=asset['preview_settings'])
