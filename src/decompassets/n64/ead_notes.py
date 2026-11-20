"""Read bounded EAD channel and layer scripts into timed note events."""

from dataclasses import dataclass, replace

from .ead_sequence import _relative, _varint, schedule

_CHANNEL_WIDTHS = {
    0xb0:2, 0xb1:0, 0xb2:2, 0xb3:1, 0xb4:0, 0xb5:0, 0xb6:0, 0xb7:2, 0xb8:1,
    0xb9:1, 0xba:1, 0xbb:3, 0xbc:2, 0xbd:4, 0xbe:0, 0xbf:0, 0xc0:0, 0xc1:1, 0xc2:2,
    0xc3:0, 0xc4:0, 0xc5:0, 0xc6:1, 0xc7:3, 0xc8:1, 0xc9:1, 0xca:1, 0xcb:2, 0xcc:1,
    0xcd:1, 0xce:2, 0xcf:2, 0xd0:1, 0xd1:1, 0xd2:1, 0xd3:1, 0xd4:1, 0xd5:1, 0xd6:1,
    0xd7:1, 0xd8:1, 0xd9:1, 0xda:2, 0xdb:1, 0xdc:1, 0xdd:1, 0xde:2, 0xdf:1, 0xe0:1,
    0xe1:3, 0xe2:2, 0xe3:1, 0xe4:0, 0xe5:1, 0xe6:1, 0xe7:2, 0xe8:8, 0xe9:1, 0xea:0,
    0xeb:2, 0xec:0, 0xed:1, 0xee:1, 0xef:3, 0xf0:0, 0xf1:1,
}
_LAYER_WIDTHS = {
    0xc5:0, 0xc7:3, 0xc8:0, 0xca:1, 0xcb:3, 0xcc:0, 0xcd:1, 0xce:1, 0xcf:1,
}
_MAX_STEPS = 65536


@dataclass
class Channel:
    program: int = 0
    font: int | None = None
    volume: int = 127
    pan: int = 64
    transpose: int = 0
    large: bool = False


@dataclass(frozen=True)
class Note:
    tick: int
    duration: int
    channel: int
    layer: int
    key: int
    velocity: int
    program: int
    font: int | None
    volume: int
    pan: int


class _Script:
    def __init__(self, data, offset, budget):
        self.data = data
        self.at = offset
        self.budget = budget
        self.stack = []
        self.loops = []
        self.visited = set()
        self.value = None
        self.conditional = False
        self.done = False

    def take(self, width=1):
        end = self.at+width
        if not 0 <= self.at <= end <= len(self.data):
            raise ValueError('EAD operand exceeds the sequence.')
        raw = self.data[self.at:end]
        self.at = end
        return int.from_bytes(raw, 'big')

    def delay(self):
        value, self.at = _varint(self.data, self.at)
        return value

    def command(self):
        while not self.done:
            state = self.at, tuple(self.stack), tuple(self.loops), self.value
            if state in self.visited:
                self.done = True
                break
            self.visited.add(state)
            self.budget[0] -= 1
            if self.budget[0] < 0:
                raise ValueError('The EAD command limit was exceeded.')
            op = self.take()
            if op < 0xf2 or op in (0xfd, 0xfe):
                return op
            if op == 0xff:
                if self.stack:
                    self.at = self.stack.pop()
                else:
                    self.done = True
            elif op == 0xf8:
                count = self.take() or 256
                if len(self.loops) >= 8:
                    raise ValueError('Too many nested EAD loops.')
                self.loops.append((self.at, count))
            elif op in (0xf6, 0xf7):
                if not self.loops:
                    raise ValueError('EAD loop terminator without a loop.')
                target, count = self.loops.pop()
                if op == 0xf7 and count > 1:
                    self.loops.append((target, count-1))
                    self.at = target
            else:
                if op <= 0xf4:
                    relative = _relative(self.take())
                    target = self.at+relative
                else:
                    target = self.take(2)
                if op == 0xfc:
                    if len(self.stack) >= 8:
                        raise ValueError('Too many nested EAD calls.')
                    self.stack.append(self.at)
                if op in (0xf4, 0xfb, 0xfc):
                    self.at = target
                elif self.value is None:
                    self.conditional = True
                elif (op in (0xf2, 0xf9) and self.value < 0 or op in (0xf3, 0xfa) and self.value == 0
                      or op == 0xf5 and self.value >= 0):
                    self.at = target
        return None


def _layer(data, offset, channel, layer, tick, stop, settings, budget):
    script = _Script(data, offset, budget)
    notes = []
    default_delay = last_delay = transpose = 0
    velocity, gate = 127, 0
    program, pan = settings.program, settings.pan
    while tick < stop and (op := script.command()) is not None:
        if op < 0xc0:
            style, key = op >> 6, (op & 63) + settings.transpose + transpose
            if settings.large:
                if style < 2:
                    last_delay = script.delay()
                length = last_delay
                velocity = script.take()
                gate = script.take() if style != 1 else 0
            else:
                length = script.delay() if style == 0 else default_delay if style == 1 else last_delay
                last_delay = length
            duration = min(stop-tick, length - ((length*gate) >> 8))
            if duration > 0 and velocity and 0 <= key <= 127:
                notes.append(Note(tick, duration, channel, layer, key, min(velocity,127),
                                  program, settings.font, settings.volume, pan))
            tick += length
        elif op in (0xc0, 0xfd):
            tick += script.delay()
        elif op == 0xfe:
            tick += 1
        elif op == 0xc1:
            velocity = script.take()
        elif op == 0xc2:
            transpose = _relative(script.take())
        elif op == 0xc3:
            default_delay = script.delay()
        elif op == 0xc6:
            choice = script.take()
            program = settings.program if choice == 255 else choice
        elif op == 0xc9:
            gate = script.take()
        elif op == 0xca:
            pan = script.take()
        elif op in _LAYER_WIDTHS:
            script.take(_LAYER_WIDTHS[op])
        elif 0xd0 <= op < 0xf0 or op in (0xc4, 0xf0, 0xf1):
            continue
        else:
            raise ValueError(f'Unsupported EAD layer command 0x{op:02X}.')
    return notes, script.conditional


def _channel(data, start, stop, settings, budget):
    script = _Script(data, start.offset, budget)
    tick = start.tick
    layers = []
    while tick < stop and (op := script.command()) is not None:
        if op == 0xfd:
            tick += script.delay()
        elif op == 0xfe:
            tick += 1
        elif op < 0x10 or 0x60 <= op < 0x70:
            tick += op & 15
        elif 0x88 <= op < 0x90 or 0x78 <= op < 0x80:
            target = script.take(2)
            if op < 0x80:
                target = script.at + (target if target < 0x8000 else target-0x10000)
            layers.append((tick, op & 7, target, replace(settings)))
        elif op in _CHANNEL_WIDTHS:
            value = script.take(_CHANNEL_WIDTHS[op])
            if op == 0xc1:
                settings.program = value
            elif op in (0xc3, 0xc4):
                settings.large = op == 0xc4
            elif op == 0xc6:
                settings.font = value
            elif op == 0xcc:
                script.value = _relative(value)
            elif op == 0xdb:
                settings.transpose = _relative(value)
            elif op == 0xdd:
                settings.pan = value
            elif op == 0xdf:
                settings.volume = value
            elif op == 0xe8:
                fields = value.to_bytes(8, 'big')
                settings.pan = fields[3]
            elif op == 0xeb:
                settings.font = value >> 8
                settings.program = value & 255
        elif 0x20 <= op < 0x30:
            # Channel script starts from channel code depend on the channel scheduler.
            script.take(2)
            script.conditional = True
        elif op < 0xb0:
            script.value = None
        else:
            raise ValueError(f'Unsupported EAD channel command 0x{op:02X}.')
    return layers, script.conditional


def notes(data, *, tick_limit=32768):
    """Return bounded timed notes and a count of unsupported channel or layer scripts."""
    root = schedule(data)
    if root is None:
        return None
    tick_limit = min(tick_limit, root['ticks'] or tick_limit)
    budget = [_MAX_STEPS]
    timed = []
    incomplete = 0
    conditional = root['conditional']
    starts = root['channels']
    for channel in range(16):
        starts_for_channel = [start for start in starts if start.channel == channel and start.tick < tick_limit]
        settings = Channel()
        for i, start in enumerate(starts_for_channel):
            stop = starts_for_channel[i+1].tick if i+1 < len(starts_for_channel) else tick_limit
            try:
                layers, branches = _channel(data, start, max(stop, start.tick+1), settings, budget)
            except (ValueError, IndexError):
                incomplete += 1
                continue
            conditional |= branches
            for j, (tick, layer, offset, state) in enumerate(layers):
                end = next((time for time, other, *_ in layers[j+1:] if other == layer), stop)
                try:
                    events, branches = _layer(data, offset, channel, layer, tick, end, state, budget)
                    timed.extend(events)
                    conditional |= branches
                except (ValueError, IndexError):
                    incomplete += 1
    return dict(notes=sorted(timed, key=lambda note: note.tick), tempos=root['tempos'],
                conditional=conditional, incomplete=incomplete, ticks=tick_limit)
