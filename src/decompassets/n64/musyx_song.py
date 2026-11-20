"""Read the bounded arrangement tables of big-endian N64 MusyX songs."""

import struct

_HEADER = struct.Struct('>6I')
_TRACKS = struct.Struct('>64I')
_REGION = struct.Struct('>IBBHhh')
_WORD = struct.Struct('>I')
MAX_SONG_BYTES = 256 * 1024
_EVENT_HEADER_SIZE = 12


def arrangement(data):
    """Return the arranged tracks and event-stream extents, or None for an unsupported layout."""
    if not _HEADER.size + _TRACKS.size + 64 <= len(data) <= MAX_SONG_BYTES:
        return None
    tracks_at, regions_at, channels_at, tempo_at, tempo, loop_tick = _HEADER.unpack_from(data)
    first_track = tracks_at + _TRACKS.size
    if (tracks_at != _HEADER.size or tempo & 0x80000000 or not 1 <= tempo <= 1000
            or not first_track < regions_at < channels_at <= len(data) - 64
            or regions_at % 4 or channels_at % 4
            or tempo_at and (tempo_at % 4 or not channels_at + 64 <= tempo_at <= len(data) - 8)):
        return None
    starts = _TRACKS.unpack_from(data, tracks_at)
    active = sorted((offset, track) for track, offset in enumerate(starts) if offset)
    if not active or active[0][0] < first_track:
        return None
    tracks = []
    region_count = 0
    for (offset, track), end in zip(active, [address for address, _ in active[1:]] + [regions_at]):
        channel = data[channels_at + track]
        if channel >= 16 or offset % 4 or not offset < end <= regions_at or (end - offset) % _REGION.size:
            return None
        clips = []
        for tick, program, _, _, region, loop in _REGION.iter_unpack(data[offset:end]):
            if region < 0:
                if region not in (-1, -2) or region == -2 and not 0 <= loop < len(clips):
                    return None
                break
            if clips and tick < clips[-1]['tick']:
                return None
            region_count = max(region_count, region + 1)
            clips.append(dict(tick=tick, program=program, region=region))
        else:
            return None
        if not clips or offset + (len(clips) + 1) * _REGION.size != end:
            return None
        tracks.append(dict(track=track, channel=channel, clips=clips, end_tick=tick,
                           loop_to=loop if region == -2 else None))
    after_table = regions_at + region_count * _WORD.size
    if after_table >= channels_at:
        return None
    starts = [offset for offset, in _WORD.iter_unpack(data[regions_at:after_table])]
    streams = []
    for offset, end in zip(starts, starts[1:] + [channels_at]):
        if offset % 4 or not after_table <= offset <= end - _EVENT_HEADER_SIZE or end > channels_at:
            return None
        streams.append((offset, end))
    return dict(tempo=tempo, loop_tick=loop_tick, tracks=tracks, streams=streams)


def events(data, start, end):
    """Read revised MUSYX region events and return their ticks and operands."""
    if not 0 <= start <= end - _EVENT_HEADER_SIZE <= len(data) - _EVENT_HEADER_SIZE:
        return None
    kind, pitch, modulation = struct.unpack_from('>3I', data, start)
    if kind != 8:
        return None
    controls = [offset for offset in (pitch, modulation) if offset]
    if any(not start + _EVENT_HEADER_SIZE < offset < end for offset in controls):
        return None
    stop = min(controls, default=end)
    at = start + _EVENT_HEADER_SIZE
    tick = 0
    result = []
    while at + 4 <= stop:
        delta, key, value = struct.unpack_from('>HBB', data, at)
        tick += delta
        if key == value == 255:
            return result if stop - (at + 4) <= 3 else None
        if key & 128:
            event = 'controller' if value == 1 or value & 128 else ('program' if value == 0 else 'internal')
            result.append(dict(tick=tick, kind=event, key=key & 127, value=value))
        elif key or value:
            if at + 6 > stop:
                return None
            duration = int.from_bytes(data[at + 4:at + 6], 'big')
            result.append(dict(tick=tick, kind='note', key=key, value=value & 127, duration=duration))
            at += 2
        at += 4
    return None
