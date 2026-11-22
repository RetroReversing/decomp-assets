import struct

import pytest

from decompassets.n64.level_world import textures


def level():
    data = bytearray(0x1000)
    base = 0x8024b000
    struct.pack_into('>I', data, 0, base+0x100)
    struct.pack_into('>I', data, 0x2c, base+0x200)
    struct.pack_into('>I', data, 0x15c, base+0x400)
    struct.pack_into('>II', data, 0x200, 1, base+0x300)
    commands = [(0xe7000000,0),(0xe3001001,0x8000),(0xfd100000,0x03000000),
                (0xf5000100,0x06000000),(0xf0000000,0x0603c000),(0xf5500000,0x07094250),
                (0xe6000000,0),(0xfd500000,0x03000020),(0xf3000000,0x070ff400),
                (0xf5400400,0x00094250),(0xf2000000,0x0007c07c),
                (0xe6000000,0),(0xdf000000,0)]
    for i, (w0,w1) in enumerate(commands):struct.pack_into('>II', data, 0x300+i*8, w0, w1)
    data[0x400:0x420] = b'\xff\xff'*16
    return data


@pytest.mark.parametrize('damage', [None, 'scene', 'table', 'opcode', 'segment', 'palette', 'pixels'])
def test_level_material_requires_bounded_ci4_commands(damage):
    data = level()
    if damage == 'scene': struct.pack_into('>I', data, 0, 0)
    if damage == 'table': struct.pack_into('>I', data, 0x200, 10000)
    if damage == 'opcode': data[0x300+7*8] = 0
    if damage == 'segment': data[0x300+7*8+4] = 4
    if damage == 'palette': data[0x400:0x420] = bytes(32)
    if damage == 'pixels': struct.pack_into('>I', data, 0x300+7*8+4, 0x03ffffff)
    rows = textures(data)
    assert len(rows) == (1 if damage is None else 0)
    if rows:
        assert (rows[0]['width'], rows[0]['height'], rows[0]['offset']) == (32,32,0x420)
