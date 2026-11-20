"""Identify relative-offset N64 MusyX program and channel tables."""

import re
import struct

from . import musyx_song

_GROUP = struct.Struct('>IHH8I')
_PAGE = struct.Struct('>HBBBB2x')
_CHANNEL = struct.Struct('>5B3x')
_SETUP = 4 + 16 * _CHANNEL.size
_END = b'\xff' * 4
_CANDIDATE = re.compile(rb'(?=\x00\x00..\x00[^\x00]\x00\x00\x00\x00\x00\x20)', re.S)


def _pages(image, start, end):
    if end - start < _PAGE.size or (end - start) % _PAGE.size or image[end-8:end] != _END * 2:
        return None
    pages = {}
    for obj, priority, voices, _, program in _PAGE.iter_unpack(image[start:end-8]):
        if program > 127 or program in pages or obj == 0xffff:
            return None
        pages[program] = dict(object_id=obj, priority=priority, voices=voices)
    return pages


def _group(image, start, limit):
    if start + _GROUP.size > limit:
        return None
    size, identifier, kind, *offsets = _GROUP.unpack_from(image, start)
    end = start + size
    if (size < _GROUP.size or size % 4 or end > limit or not 0 < identifier < 256 or kind
            or offsets[0] != 32 or any(offset < 32 or offset + 8 >= size for offset in offsets)
            or image[end-4:end] != _END):
        return None
    pages_at, drums_at, setups_at = (start + 8 + offset for offset in offsets[-3:])
    pages = _pages(image, pages_at, drums_at)
    drums = _pages(image, drums_at, setups_at)
    if not pages or drums is None or (end-4-setups_at) % _SETUP or setups_at >= end-4:
        return None
    setups = {}
    for pos in range(setups_at, end-4, _SETUP):
        song, reserved = struct.unpack_from('>HH', image, pos)
        if song > 255 or reserved or song in setups:
            return None
        channels = list(_CHANNEL.iter_unpack(image[pos+4:pos+_SETUP]))
        if any(channel[0] > 127 and channel[0] != 255 for channel in channels):
            return None
        setups[song] = channels
    return identifier, end, dict(offset=start, pages=pages, drums=drums, setups=setups)


def locate(image, limit, songs, check=lambda: None):
    """Require a contiguous project with an exact cross-match to indexed song IDs."""
    expected = {(group, song) for _, _, group, song in songs}
    start_bound = max(0, limit - 1024 * 1024)
    for hit in _CANDIDATE.finditer(image, start_bound, limit):
        start = hit.start()
        if start % 4:
            continue
        check()
        offset = start
        groups = {}
        pairs = set()
        while record := _group(image, offset, limit):
            identifier, offset, group = record
            found = {(identifier, song) for song in group['setups']}
            if identifier in groups or not found <= expected:
                break
            groups[identifier] = group
            pairs.update(found)
            if pairs == expected:
                if offset + 4 <= limit and image[offset:offset+4] == _END:
                    return dict(offset=start, end=offset + 4, groups=groups)
                break
    return None


_POOL = struct.Struct('>4I')
_OBJECT = struct.Struct('>IH2x')


def _objects(image, start, end, tag):
    objects = {}
    while start + _OBJECT.size <= end:
        size, identifier = _OBJECT.unpack_from(image, start)
        if (size < _OBJECT.size or size % 4 or start+size > end
                or identifier >> 14 != tag or identifier in objects):
            return None
        objects[identifier] = (start+_OBJECT.size, start+size)
        start += size
    return objects if start == end and objects else None


def find_pool(image, start, limit, required):
    """Find the object pool whose IDs resolve every program used by the indexed songs."""
    if not required:
        return None
    for base in range(start, min(start+4096, limit-_POOL.size+1), 4):
        macros, tables, keymaps, layers = _POOL.unpack_from(image, base)
        if not macros == _POOL.size < tables < keymaps < layers < limit-base:
            continue
        for tail in (limit, limit-4):
            ends = (base+tables, base+keymaps, base+layers, tail)
            starts = (base+macros, *ends[:-1])
            if not ends[-2] < tail or any(image[end-4:end] != _END for end in ends):
                continue
            sections = [_objects(image, lo, hi-4, tag)
                        for lo, hi, tag in zip(starts, ends, (0, 3, 1, 2))]
            if all(sections) and required <= set().union(*sections):
                return dict(offset=base, end=tail, objects=dict(zip(
                    ('macro', 'table', 'keymap', 'layer'), sections)))
    return None


def used_programs(image, songs, groups):
    """Resolve every note to the song's initial or explicitly selected program."""
    required = set()
    for start, end, group_id, song_id in songs:
        if not 0 <= start < end <= len(image) or end-start > musyx_song.MAX_SONG_BYTES:
            return None
        data = image[start:end]
        arrangement = musyx_song.arrangement(data)
        if arrangement is None:
            return None
        streams = [musyx_song.events(data, lo, hi) for lo, hi in arrangement['streams']]
        if any(stream is None for stream in streams):
            return None
        group = groups[group_id]
        for track in arrangement['tracks']:
            channel = track['channel']
            program = group['setups'][song_id][channel][0]
            pages = group['drums'] if channel == 9 else group['pages']
            for clip in track['clips']:
                if clip['program'] != 255:
                    program = clip['program']
                for event in streams[clip['region']]:
                    if event['kind'] == 'program':
                        program = event['key']
                    elif event['kind'] == 'note':
                        page = pages.get(program)
                        if page is None:
                            return None
                        required.add(page['object_id'])
    return required
