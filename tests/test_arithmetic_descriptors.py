import struct

from decompassets import n64
from decompassets.n64 import arithmetic_descriptors as descriptors


def fixture(*, target=0x80001000, width=2):
    data = bytearray(1024)
    loader = [*descriptors._LOADER, 0x0c000000 | ((target>>2)&0x3ffffff)]
    struct.pack_into('>6I', data, 0, *loader)
    struct.pack_into('>4I', data, 128, *descriptors._DECODER)
    struct.pack_into('>BB5H4I', data, 256, 4, 1, width, 2, 2, 2, 0, 0, 0, 0xb0000300, 0xb0000308)
    data[768:776] = bytes.fromhex('00000004ca56fac0')
    functions = [dict(name='descriptor_loader',vram=0x80000000,rom_offset=0,size=128),
                 dict(name='decoder',vram=0x80001000,rom_offset=128,size=128)]
    return bytes(data), dict(functions=functions)


def test_packed_texture_descriptor_bounds_the_dimensions_and_decode():
    image, context = fixture()
    asset, = [row for row in n64.regions(image,context=context) if row.get('layout')==descriptors.LAYOUT]
    assert asset['offset']==768 and asset['size']==8
    assert n64.preview(image,asset,{})['media']=='image'


def test_wrong_loader_target_and_wrong_expanded_dimensions_are_rejected():
    for options in (dict(target=0x80002000),dict(width=3)):
        image,context = fixture(**options)
        assert descriptors.regions(image,context=context)==[]
