import struct

from decompassets.n64.rnc_adpcm import samples, wave_base


def test_control_records_match_only_one_complete_wave_area():
    control = bytearray(8*176)
    image = bytearray(b'\xff' * 2048)
    for i in range(8):
        book = 24+i*176
        offset = i*48
        struct.pack_into('>II', control, book-24, offset, 45)
        struct.pack_into('>I', control, book-8, 0x4000+book)
        struct.pack_into('>II', control, book, 2, 4)
        for frame in range(5):
            image[512+offset+frame*9:512+offset+frame*9+9] = bytes([0x10+i%4])+bytes([i+1]*8)
    rows = samples(control)
    assert len(rows) == 8
    assert wave_base(image, rows) == 512
    image[512+7*48+9] = 0x1f
    assert wave_base(image, rows) is None
    control[16] ^= 1
    assert samples(control) == []
