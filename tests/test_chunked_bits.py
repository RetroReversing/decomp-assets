"""Bounded bitstream resources and their indexed image previews."""
import struct

from decompassets.n64 import chunked_bits, chunked_lz_images


def pack_bits(value):
    value += '0' * (-len(value) % 8)
    return bytes(int(value[i:i+8], 2) for i in range(0, len(value), 8))


def test_literals_and_backreferences():
    payload = '1' + f'{3:07b}' + ''.join(f'{b:08b}' for b in b'abc') + '0' + '1' + '11'
    stream = b'\x03\0\0\x10\0' + pack_bits(payload)
    assert chunked_bits.decode(stream, 6) == b'abcabc'
    assert chunked_bits.decode(stream[:-1], 6) is None
    assert chunked_bits.decode(stream, 5) is None
    assert chunked_lz_images.decode(stream, 6) == b'abcabc'


def test_window_limit_across_input_pages():
    literal = b'\xff' + b'A' * 127
    first = b'\x03\0\0\x10\0' + literal * 31 + b'\xfa' + b'A' * 122
    stream = first + literal * (32 * 16) + pack_bits('0' + '1' + f'{1:016b}')
    expected = 31 * 127 + 122 + 32 * 16 * 127 + 3
    assert chunked_bits.decode(stream, expected) == b'A' * expected


def test_bitstream_image_reaches_the_same_preview():
    data = (struct.pack('>4HI2H', 8, 1, 1, 0xffff, 72, 8, 8)
            + bytes(range(64)) + b'\x02\x06\x01\x00\x00\x08' + bytes(512))
    stream = b'\x03\0\0\x10\0' + b''.join(
        bytes([0x80 | len(piece)]) + piece for piece in (data[i:i+127] for i in range(0, len(data), 127)))
    offset, headers, body = 36, [], bytearray()
    for _ in range(3):
        headers.append(struct.pack('>III', offset, len(data), 0x80000000 | len(stream)))
        body.extend(stream)
        if len(body) % 2:
            body.append(0)
        offset = 36 + len(body)
    image = b''.join(headers) + body
    rows = chunked_lz_images.regions(image)
    assert len(rows) == 3 and rows[0]['width'] == 8
    assert chunked_lz_images.preview(image, rows[0], {})['media'] == 'image'
