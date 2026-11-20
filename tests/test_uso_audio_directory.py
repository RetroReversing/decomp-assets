import struct

from decompassets.n64 import uso_audio_directory
from decompassets.n64.audio import vadpcm


def _table(rows):
    return struct.pack('>H14x', len(rows)) + b''.join(
        struct.pack('>II2B6x', offset, size, 2, 0) for offset, size in rows
    )


def test_sequence_directory_requires_complete_tables_and_font_links():
    fonts = _table([(i*16, 16) for i in range(8)])
    sequences = _table([(i*16, 16) for i in range(7)] + [(2, 0)])
    links = struct.pack('>8H', *range(16, 32, 2)) + bytes([1, 0]) * 8
    waves = _table([(0, 48)])
    image = fonts + links + sequences + waves
    directory = uso_audio_directory.locate(image, 128, 112, 48)
    assert directory is not None
    asset = uso_audio_directory.asset(directory, 1000)
    assert asset['sequences'][-1] == dict(sequence=7, alias=2, offset=1032, bytes=16, fonts=[0])
    assert uso_audio_directory.locate(image, 128, 128, 48) is None
    broken = bytearray(image)
    broken[len(fonts)+17] = 8
    assert uso_audio_directory.locate(broken, 128, 112, 48) is None


def test_two_bit_adpcm_uses_four_signed_residuals_per_byte():
    raw = bytes([0x20, 0x1b, 0x1b, 0x1b, 0x1b])
    assert struct.unpack('<16h', vadpcm(raw, [0]*16, 1, 16, bits=2)) == (0, 4, -8, -4)*4
