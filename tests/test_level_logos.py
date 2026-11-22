import struct

import pytest

from decompassets.n64 import level_logos


def cartridge():
    data = bytearray(0x30000)
    struct.pack_into('>I', data, 8, 0x80000400)
    for i in range(8):
        pos = 0x2000 + 0x54*i
        name = 0x3000 + i*16
        data[name:name+6] = f'lev{i:02}'.encode()+b'\0'
        struct.pack_into('>I', data, pos, name + 0x7ffff400)
        struct.pack_into('>6I', data, pos+0x1c, 0x4000+i*16, 0x4010+i*16,
                         0x5000+i*16, 0x5010+i*16, 0x80101000, 0x80100000)
        logo = 0x10000+i*0x820
        struct.pack_into('>I', data, pos+0x3c, logo)
        data[logo:logo+32] = b'\xff\xff'*16
    return data


@pytest.mark.parametrize('damage', [None, 'bad_name', 'bad_range', 'bad_address', 'bad_logo'])
def test_level_directory_requires_bounded_records(damage):
    data = cartridge()
    if damage == 'bad_name': data[0x3000:0x3006] = b'\xff'*6
    if damage == 'bad_range': struct.pack_into('>I', data, 0x2000+0x20, len(data)+1)
    if damage == 'bad_address': struct.pack_into('>I', data, 0x2000+0x30, 0)
    if damage == 'bad_logo': struct.pack_into('>I', data, 0x2000+0x3c, len(data)-4)
    result = level_logos.regions(data)
    assert len(result) == (8 if damage is None else 0)
    if result:
        preview = level_logos.preview(data, result[0], {})
        assert preview['mime'] == 'image/png'
        assert preview['details']['width'] == 64
