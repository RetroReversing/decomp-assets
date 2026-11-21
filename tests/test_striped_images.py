import struct

from decompassets import formats
from decompassets.n64 import striped_images


def test_striped_images_require_consecutive_complete_tables():
    image = bytearray(64)
    for pixel, stride in ((b'\xf8\x01', 2), (b'\x07\xc1', 2), (b'\x88', 1)):
        offset = len(image) - 64
        pixels = pixel * (320 * 240)
        image.extend(pixels)
        for strip in range(20 * stride):
            image.extend(struct.pack('>I', offset + strip * 0xf00))
    assets = striped_images.regions(image)
    assert [asset['preview_settings']['format'] for asset in assets] == ['rgba5551-be', 'rgba5551-be', 'i8']
    result = formats.preview(image, assets[-1]['preview_settings'])
    assert result['media'] == 'image'
    assert not striped_images.regions(image[:-1])
    image[-1] ^= 1
    assert not striped_images.regions(image)
