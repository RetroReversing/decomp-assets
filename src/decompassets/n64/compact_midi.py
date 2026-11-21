"""Bounded first-pass decoding of Nintendo's libultra compressed MIDI."""

import struct
from dataclasses import dataclass

_HEADER = struct.Struct('>17I')
_MAX_EVENTS = 65536
_LENGTH = {0x80: 2, 0x90: 2, 0xa0: 2, 0xb0: 2, 0xc0: 1, 0xd0: 1, 0xe0: 2}


@dataclass(frozen=True)
class Event:
    tick: int
    status: int
    data: tuple[int, ...]
    duration: int = 0


class _Track:
    def __init__(self, data, start, end):
        self.data = data
        self.at = start
        self.end = end
        self.back = self.back_end = 0

    def byte(self, *, compressed=True):
        if self.back < self.back_end:
            value = self.data[self.back]
            self.back += 1
            return value
        if self.at >= self.end:
            raise ValueError
        start = self.at
        self.at += 1
        value = self.data[start]
        if value != 0xfe or not compressed:
            return value
        if self.at >= self.end:
            raise ValueError
        if self.data[self.at] == 0xfe:
            self.at += 1
            return value
        if self.at+3 > self.end:
            raise ValueError
        distance, length = struct.unpack_from('>HB', self.data, self.at)
        self.at += 3
        self.back = start-distance
        self.back_end = self.back+length
        if self.back < _HEADER.size or not length or self.back_end > start:
            raise ValueError
        return self.byte()

    def variable(self):
        result = 0
        for _ in range(4):
            value = self.byte()
            result = result*128+(value & 127)
            if value < 128:
                return result
        raise ValueError

    def events(self, budget):
        tick = running = 0
        while budget[0]:
            budget[0] -= 1
            tick += self.variable()
            value = self.byte()
            if value == 0xff:
                kind = self.byte()
                running = 0
                if kind == 0x2f:
                    return
                if kind == 0x51:
                    tempo = tuple(self.byte() for _ in range(3))
                    if not any(tempo):
                        raise ValueError
                    yield Event(tick, 0xff, tempo)
                elif kind == 0x2e:
                    self.byte()
                    if self.byte() != 0xff:
                        raise ValueError
                elif kind == 0x2d:
                    self.byte()
                    self.byte()
                    for _ in range(4):
                        self.byte(compressed=False)
                else:
                    raise ValueError
                continue
            if value >= 128:
                running = value
                fields = ()
            else:
                fields = (value,)
            command = running & 0xf0
            if command not in _LENGTH:
                raise ValueError
            fields += tuple(self.byte() for _ in range(_LENGTH[command]-len(fields)))
            if any(field >= 128 for field in fields):
                raise ValueError
            yield Event(tick, running, fields, self.variable() if command == 0x90 else 0)
        raise ValueError


def sequence(data):
    """Return the division and time-ordered events, walking sequence loops once."""
    if not _HEADER.size < len(data) <= 256*1024:
        return None
    *offsets, division = _HEADER.unpack_from(data)
    starts = [at for at in offsets if at]
    if (not starts or starts != sorted(set(starts)) or starts[0] != _HEADER.size
            or starts[-1] >= len(data) or not 1 <= division <= 0x7fff):
        return None
    try:
        budget = [_MAX_EVENTS]
        tracks = [_Track(data, at, end).events(budget)
                  for at, end in zip(starts, starts[1:]+[len(data)])]
        events = sorted((event for track in tracks for event in track), key=lambda event: event.tick)
    except ValueError:
        return None
    return division, events
