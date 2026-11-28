import struct

from decompassets.n64 import chunked_lz_images as images


def packed(data):
    parts = [b'\x01\x00\x00\x10\x00']
    for start in range(0, len(data), 127):
        piece = data[start:start + 127]
        parts.append(bytes([0x80 | len(piece)]) + piece)
    return b''.join(parts) + b'\x00'


def image():
    return (struct.pack('>4HI2H', 8, 1, 1, 0xffff, 72, 8, 8)
            + bytes(range(64)) + b'\x02\x06\x01\x00\x00\x08' + bytes(512))


def directory():
    data = image()
    source = packed(data)
    offset = 36
    entries = []
    body = bytearray()
    for _ in range(3):
        entries.append(struct.pack('>III', offset, len(data), 0x80000000 | len(source)))
        body.extend(source)
        if len(body) % 2:
            body.append(0)
        offset = 36 + len(body)
    return b''.join(entries) + body


def test_directory_and_preview():
    data = directory()
    rows = images.regions(data)
    assert len(rows) == 3
    assert images.image_info(images.decode(data[rows[0]['offset']:][:rows[0]['size']], rows[0]['expanded'])) == (8, 8, 86)
    assert images.preview(data, rows[0], {})


def test_reject_invalid_data_and_directory():
    data = bytearray(directory())
    data[12:16] = struct.pack('>I', 99)
    assert not list(images.directories(data))
    assert images.decode(b'12345\x01\xff\xff\x00', 1) is None
    assert images.decode(packed(image())[:-5], len(image())) is None
    assert images.image_info(image()[:-1]) is None


def test_copy_across_chunks():
    source = bytearray(b'12345' + b'\x81A' + b'\x00')
    source.extend(bytes(0x1000-len(source)))
    source.extend(b'\x03\x01\x00\x00')
    assert images.decode(source, 4) == b'AAAA'
