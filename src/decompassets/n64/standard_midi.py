"""Read bounded format-0 Standard MIDI for a sample-backed preview."""

import struct
from collections import defaultdict, deque
from dataclasses import replace

from .compact_midi import _LENGTH, _MAX_EVENTS, Event

_HEADER = struct.Struct('>4sIHHH4sI')


def sequence(data):
    if not _HEADER.size < len(data) <= 256*1024:
        return None
    tag, length, format_, tracks, division, track, track_size = _HEADER.unpack_from(data)
    if (tag != b'MThd' or length != 6 or format_ or tracks != 1 or track != b'MTrk'
            or not 1 <= division < 32768 or track_size != len(data)-_HEADER.size):
        return None
    at = _HEADER.size
    tick = running = 0
    pending = defaultdict(deque)
    events = []

    def byte():
        nonlocal at
        if at >= len(data):
            raise ValueError
        value = data[at]
        at += 1
        return value

    def variable():
        result = 0
        for _ in range(4):
            value = byte()
            result = 128*result+(value&127)
            if value < 128:
                return result
        raise ValueError

    try:
        for _ in range(_MAX_EVENTS):
            tick += variable()
            first = byte()
            if first == 0xff:
                kind = byte()
                size = variable()
                if at+size > len(data):
                    return None
                if kind == 0x2f:
                    return (division,events) if size == 0 and at == len(data) else None
                if kind == 0x51:
                    tempo = tuple(data[at:at+size])
                    if size != 3 or not any(tempo):
                        return None
                    events.append(Event(tick,0xff,tempo))
                at += size
                running = 0
                continue
            if first in (0xf0,0xf7):
                size = variable()
                at += size
                running = 0
                continue
            if first >= 128:
                running, fields = first,()
            else:
                fields = (first,)
            command = running&0xf0
            if command not in _LENGTH:
                return None
            fields += tuple(byte() for _ in range(_LENGTH[command]-len(fields)))
            if any(value >= 128 for value in fields):
                return None
            if command in (0x80,0x90):
                key = (running&15,fields[0])
                if command == 0x90 and fields[1]:
                    pending[key].append(len(events))
                    events.append(Event(tick,running,fields))
                elif pending[key]:
                    index = pending[key].popleft()
                    events[index] = replace(events[index],duration=tick-events[index].tick)
            else:
                events.append(Event(tick,running,fields))
    except ValueError:
        return None
    return None
