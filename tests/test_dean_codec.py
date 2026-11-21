import base64
import io
import math
import struct
import wave

import pytest

from decompassets.formats import AssetError
from decompassets.n64 import dean_audio, dean_codec


def _tree(symbols):
    nodes = []

    def add(leaves):
        index = len(nodes)
        nodes.append(None)
        if len(leaves) == 1:
            nodes[index] = (0x800, leaves[0])
        else:
            middle = len(leaves) // 2
            nodes[index] = (add(leaves[:middle]), add(leaves[middle:]))
        return index

    nodes.append((1, 2))
    nodes.append((0x800, symbols[0]))
    nodes.append((3, 4))
    nodes.append((0x800, symbols[1]))
    add(symbols[2:])
    return b''.join(dean_codec.NODE.pack(*node) for node in nodes)


def _image(padding=24, bias=0x80000000):
    image = bytearray(dean_codec.BAND_SIGNATURE)
    image.extend(struct.pack('>64f', *[1 / 32768] * 64))
    image.extend(bytes(padding))
    descriptor = len(image)
    section = descriptor + 4 * dean_codec.DESCRIPTOR.size + 4
    image.extend(bytes(section - descriptor))
    for i, (start, size) in enumerate(((0, 16), (0, 35), (35, 89), (124, 132))):
        image.extend(dean_codec.SECTION.pack(int(i == 0), start, size, 0,
                                            bias + descriptor + (i - 1) % 4 * dean_codec.DESCRIPTOR.size))
    for i in range(4):
        tree = len(image)
        limit = 127 if i < 3 else 64
        literals = [v & 65535 for v in range(-limit, limit + 1) if v != 1]
        nodes = [0xb00, 1, 0x900, *literals] if i < 3 else [0, 1, *literals[1:]]
        image.extend(_tree(nodes))
        dean_codec.DESCRIPTOR.pack_into(image, descriptor + i * dean_codec.DESCRIPTOR.size,
                                        -limit, limit, 0, 16, 0, 256 if i < 3 else 129, 0, 0,
                                        (tree + bias + 2**31)%2**32 - 2**31)

    payload = bytes(12) + b'\x80\0' + bytes(2)
    stream = struct.pack('>III', 11025, 2, len(payload)) + payload
    record = b'RAW!' + struct.pack('>I', len(stream)) + stream + b'END!'
    image.extend(b''.join(struct.pack('>III', 24 + i * len(record), len(stream), sum(stream)) for i in range(2)))
    image.extend(record * 2)
    return bytes(image)


def test_dean_preview_decodes_pcm_with_rom_codebooks():
    image = _image()
    stream, _ = dean_audio.regions(image)
    assert stream['dean_codebooks'] == 0
    assert stream['samples'][0]['samples'] == 128
    preview = dean_audio.preview(image, stream, {})
    assert preview['details']['format'] == 'Acclaim DEAN'
    with wave.open(io.BytesIO(base64.b64decode(preview['data_url'].split(',', 1)[1]))) as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes()) == (1, 2, 11025, 128)
        samples = struct.unpack('<128h', wav.readframes(128))

    # The first block contains only the DC coefficient. Its FFT is constant.
    angle = 2 * math.pi / 2048
    index = 32
    phase = 2 * math.pi * index / 512
    expected = round(32768 * math.sin(angle + phase - math.pi / 4) * math.sin((4 * index + 1) * angle))
    assert samples[index] == expected and samples[0] < 0 < samples[-1]


def test_dean_rejects_invalid_codebook_pointer_and_truncated_frame():
    image = _image()
    damaged = bytearray(image)
    descriptor = len(dean_codec.BAND_SIGNATURE) + 64 * 4 + 24
    damaged[descriptor + 32] = 0
    assert dean_codec.table_offset(bytes(damaged)) is None
    with pytest.raises(AssetError, match='ends inside a frame'):
        dean_codec.decode(image, 0, bytes(12), 1)
