from decompassets.n64 import sprite_constructor


def test_sprite_calls_require_constructor_and_unambiguous_mapping():
    image = bytearray(2048)
    image[:len(sprite_constructor._PREFIX)] = sprite_constructor._PREFIX
    image[16:16+len(sprite_constructor._SHAPE)] = sprite_constructor._SHAPE
    image[512:1536] = bytes(range(256))*4
    functions = [dict(vram=0x80000000, rom_offset=0, size=64),
                 dict(vram=0x80000040, rom_offset=64, size=64)]

    def read(vram, code, **kwargs):
        if vram != 0x80000040:
            return dict(events=[])
        return dict(events=[dict(kind='call', target=0x80000000,
                                 args=[None, None, dict(kind='constant', value=address)])
                            for address in (0x80000200, 0x80000400)])

    context = dict(functions=functions, segments=[dict(vram=0x80000000, rom_start=0, rom_end=2048)], read_code=read)
    assert [row['offset'] for row in sprite_constructor.regions(image, context=context)] == [512, 1024]
    image[16] ^= 1
    assert sprite_constructor.regions(image, context=context) == []
