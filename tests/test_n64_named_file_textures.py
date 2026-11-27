import struct

from decompassets.n64 import named_file_textures


def fixture():
    data = bytearray(0x400)
    names = [f'FILE{i:04}.TEX'.encode() for i in range(8)]
    start = 0x200
    for i, name in enumerate(names):
        name_at = 0x100 + i * 16
        data[name_at:name_at+len(name)+1] = name + b'\0'
        struct.pack_into('>7I', data, i*28, 0x80010000 + name_at, 0, 16, 16, 0, start, start+16)
        data[start:start+16] = bytes.fromhex('0202000000000000f80107c1003fffff')
        start += 16
    return bytes(data)


def test_named_table_textures_and_bounds():
    data = fixture()
    assets = named_file_textures.regions(data)
    assert len(assets) == 8
    assert named_file_textures.preview(data, assets[0], {})['mime'] == 'image/png'
    damaged = bytearray(data)
    struct.pack_into('>I', damaged, 20, len(data) + 16)
    assert len(named_file_textures.regions(damaged)) == 0
