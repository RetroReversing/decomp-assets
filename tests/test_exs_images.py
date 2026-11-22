"""EXS streams are terminated and bounded before preview."""

from decompassets.n64 import exs_images


def test_literals_backreferences_and_terminator():
    stream = b'\x03AB\x01\x10\0\0'
    assert exs_images.unpack(stream, 0, 5) == (b'ABABA', len(stream))
    assert exs_images.unpack(stream[:-1], 0, 5) is None
    assert exs_images.unpack(stream, 0, 4) is None
    assert exs_images.unpack(b'\0\x01\x10', 0, 3) is None


def test_checked_background_preview():
    pixels = bytes(304 * 208)
    palette = bytes(range(256)) * 2
    data = pixels + palette
    encoded = b''.join(b'\xff' + data[i:i+8] for i in range(0, len(data), 8)) + bytes(3)
    image = b'EXS\x01' + len(data).to_bytes(4, 'little') + encoded
    asset, = exs_images.regions(image)
    assert exs_images.preview(image, asset, {})['details']['width'] == 304
    assert exs_images.regions(image[:-1]) == []


def test_texture_bank_selects_the_requested_frame():
    import struct

    count = 2
    descriptor = 24 + count * 8
    palette = descriptor + count * 24
    data = bytearray(palette + count * 32 + count * 8)
    data[:8] = b'_GTNEVR1'
    struct.pack_into('>2I', data, 16, count, 4)
    for i in range(count):
        struct.pack_into('>2H', data, descriptor + i * 24 + 4, 4, 4)
    encoded = b''.join(b'\xff' + data[i:i+8] for i in range(0, len(data), 8)) + bytes(3)
    image = b'EXS\x01' + len(data).to_bytes(4, 'little') + encoded
    asset, = exs_images.regions(image)
    assert asset['frames'] == 2
    assert exs_images.preview(image, asset, {'frame': 1})['details']['width'] == 4
    data[descriptor + 4:descriptor + 8] = bytes(4)
    assert exs_images.bank(data) == []
