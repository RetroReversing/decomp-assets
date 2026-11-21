import struct

from decompassets.n64 import mwo_graphics


def test_mode_one_counts_tokens_and_copies_from_absolute_ring_offsets():
    # One literal, then a six-byte overlapping copy from the initial write position.
    packed = b'\x01' + struct.pack('>I', 2) + b'\x01A\xee\xf3'
    assert mwo_graphics.inflate(packed + b'\0\0') == (b'A' * 7, len(packed))
    assert mwo_graphics.inflate(packed[:-1]) is None


def test_mode_one_initial_dictionary_is_zero_filled():
    packed = b'\x01' + struct.pack('>I', 1) + b'\0\x7f\x05'
    assert mwo_graphics.inflate(packed) == (bytes(8), len(packed))


def test_packed_bytes_without_overlay_loader_evidence_are_not_assets():
    packed = b'\x01' + struct.pack('>I', 1) + b'\x01A'
    assert mwo_graphics.regions(packed) == []


def test_loader_descriptor_is_resolved_in_its_own_overlay():
    image = bytearray(0x200)
    resident, overlay, staging, destination = 0x80001000, 0x80100000, 0x80300000, 0x80200000
    image[0x10:0x18] = bytes.fromhex('908700002ce1000a')
    image[0x40:0x44] = b'MWo2'
    struct.pack_into('>3I', image, 0xa0, staging, 0x180, 0x188)
    image[0x180:0x188] = b'\x01\0\0\0\x01\x01A\0'
    owner = dict(rom_start=0x80, rom_end=0xc0, vram=overlay)
    segments = [dict(rom_start=0x10, rom_end=0x40, vram=resident), owner,
                dict(rom_start=0xc0, rom_end=0x100, vram=overlay)]

    def constant(value):
        return dict(kind='constant', value=value)

    def read(*args, **kwargs):
        return dict(events=[
            dict(kind='call', block=0, instruction=0, args=[constant(overlay+0x20)]),
            dict(kind='call', block=0, instruction=12, target=resident,
                 args=[constant(staging), constant(destination)]),
        ])

    context = dict(segments=segments, functions=[dict(vram=overlay, rom_offset=0x80, size=16)], read_code=read)
    assert list(mwo_graphics.loads(image, context, lambda: None)) == [(owner, 0x180, 7, 0x200000, b'A')]
    image[0x187] = 1
    assert list(mwo_graphics.loads(image, context, lambda: None)) == []
