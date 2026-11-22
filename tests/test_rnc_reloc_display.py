import struct

from decompassets.n64.rnc_reloc_display import mesh


def fixture():
    data = bytearray(128)
    struct.pack_into('>4I', data, 0, 96, 2, 100, 108)
    for i, point in enumerate(((0, 0, 0), (5, 0, 0), (0, 5, 0))):
        struct.pack_into('>3h', data, 32+16*i, *point)
    struct.pack_into('>8I', data, 96, 0xfd100000, 32, 0x04000c2f, 32,
                     0xbf000000, 0x00000204, 0xb8000000, 0)
    return data


def test_closed_relocated_display_list_and_bad_references():
    data = fixture()
    row = mesh(data)
    assert row is not None and row[2] == [(0, 1, 2)]
    struct.pack_into('>I', data, 108, 120)
    assert mesh(data) is None
    data = fixture()
    struct.pack_into('>I', data, 124, 1)
    assert mesh(data) is None
