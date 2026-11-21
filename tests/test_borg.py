import struct

from decompassets.n64 import borg


def _archive():
    # Type 8 stores the RGBA palette before its index data.
    texture = struct.pack('>4HII', 4, 8, 1, 0, 16, 528)+bytes(512)+bytes(8)
    count = 32
    payload = texture*count
    rows = b''.join(struct.pack('>HHIII', 8, 0, len(texture), len(texture), i*len(texture))
                    for i in range(count))
    return payload+struct.pack('>II', count, len(payload))+rows


def test_borg_directory_and_texture_preview():
    rom = _archive()
    assets = borg.regions(rom)
    assert len(assets) == 32
    result = borg.preview(rom, assets[0], {})
    assert result['details']['width'] == 8
    assert result['data_url'].startswith('data:image/png;base64,')
    assert not borg.regions(rom[:-1])


def _packed_example():
    stream = bytearray()
    left = 0
    marker = 0

    def bit(value):
        nonlocal left, marker
        if not left:
            marker = len(stream)
            stream.append(0)
            left = 8
        left -= 1
        stream[marker] |= value << left

    def prefix(code):
        digits = bin(code)[3:]
        for i, digit in enumerate(digits):
            bit(int(digit))
            bit(i == len(digits)-1)

    # One literal, followed by three overlapping bytes at distance one.
    bit(1)
    stream.append(ord('X'))
    bit(0)
    prefix(2)
    bit(1)
    bit(0)
    bit(0)
    prefix(0x1000002)
    stream.append(0xff)
    return bytes(stream)


def test_borg_lzb_checks_extent_and_overlapping_matches():
    import pytest

    from decompassets.formats import AssetError
    from decompassets.n64 import borg_lzb

    encoded = _packed_example()
    assert borg_lzb.unpack(encoded, 4) == b'XXXX'
    with pytest.raises(AssetError):
        borg_lzb.unpack(encoded, 3)
    with pytest.raises(AssetError):
        borg_lzb.unpack(encoded[:-1], 4)
