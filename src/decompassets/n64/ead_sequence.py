"""Bounded channel-start schedules for Nintendo EAD sequence previews."""

from dataclasses import dataclass

_ROOT_WIDTHS = {
    0xC1:1, 0xC6:1, 0xC7:3, 0xC8:1, 0xC9:1, 0xCC:1, 0xD0:1, 0xD1:1,
    0xD2:2, 0xD3:1, 0xD5:1, 0xD6:2, 0xD7:2, 0xD8:1, 0xDA:3, 0xDB:1,
    0xDC:1, 0xDD:1, 0xDE:2, 0xDF:1, 0xF1:1,
}
_MAX_COMMANDS = 8192
_MAX_DEPTH = 8


@dataclass(frozen=True)
class ChannelStart:
    tick: int
    channel: int
    offset: int


def _varint(data, at):
    value = data[at]
    at += 1
    if value & 128:
        value = ((value & 127) << 8) | data[at]
        at += 1
    return value, at


def _relative(value):
    return value if value < 128 else value-256


def schedule(data):
    """Read one pass of the root script, retaining channel starts and tempo changes."""
    at = tick = 0
    stack = []
    loops = []
    visited = set()
    starts = []
    tempos = [(0, 120)]
    value = None
    conditional = False
    try:
        for _ in range(_MAX_COMMANDS):
            if not 0 <= at < len(data):
                return None
            state = at, tuple(stack), tuple(loops), value
            if state in visited:
                return dict(channels=starts, tempos=tempos, ticks=tick, loops=True, conditional=conditional) if starts else None
            visited.add(state)
            op = data[at]
            at += 1
            if op == 0xff:
                if stack:
                    at = stack.pop()
                    continue
                return dict(channels=starts, tempos=tempos, ticks=tick, loops=False, conditional=conditional) if starts else None
            if op == 0xfe:
                tick += 1
            elif op == 0xfd:
                delay, at = _varint(data, at)
                tick += delay
            elif 0x90 <= op < 0xb0:
                target = (data[at] << 8) | data[at+1]
                at += 2
                if op >= 0xa0:
                    target = at + (target if target < 0x8000 else target-0x10000)
                if not 0 <= target < len(data):
                    return None
                starts.append(ChannelStart(tick, op & 15, target))
            elif op in (0xfb, 0xfc):
                target = (data[at] << 8) | data[at+1]
                if op == 0xfc:
                    if len(stack) >= _MAX_DEPTH:
                        return None
                    stack.append(at+2)
                at = target
            elif op in (0xf2, 0xf3, 0xf5, 0xf9, 0xfa):
                relative = op in (0xf2, 0xf3)
                if relative:
                    jump = _relative(data[at])
                    at += 1
                    target = at+jump
                else:
                    target = (data[at] << 8) | data[at+1]
                    at += 2
                if value is None:
                    # Record the fall-through schedule. Runtime channel I/O can select another branch.
                    conditional = True
                elif (op in (0xf2, 0xf9) and value < 0
                      or op in (0xf3, 0xfa) and value == 0
                      or op == 0xf5 and value >= 0):
                    at = target
            elif op == 0xf4:
                at += 1 + _relative(data[at])
            elif op == 0xf8:
                if len(loops) >= _MAX_DEPTH:
                    return None
                loops.append((at+1, data[at] or 256))
                at += 1
            elif op in (0xf6, 0xf7):
                if not loops:
                    return None
                begin, remaining = loops.pop()
                if op == 0xf7 and remaining > 1:
                    loops.append((begin, remaining-1))
                    at = begin
            elif op in _ROOT_WIDTHS:
                if at+_ROOT_WIDTHS[op] > len(data):
                    return None
                if op == 0xcc:
                    value = _relative(data[at])
                elif op == 0xc8 and value is not None:
                    value -= _relative(data[at])
                elif op == 0xc9 and value is not None:
                    value &= data[at]
                if op == 0xdd:
                    bpm = data[at]
                    if bpm == 0:
                        return None
                    tempos.append((tick, bpm))
                at += _ROOT_WIDTHS[op]
            elif op < 0x10 or 0x50 <= op < 0x60 or 0x80 <= op < 0x90:
                value = None
            elif op < 0x60 or 0x70 <= op < 0x80:
                # Player I/O commands without an immediate operand.
                continue
            else:
                return None
    except IndexError:
        return None
    return None
