import struct

from decompassets.n64 import ptr_audio, ptr_audio_v1


def fixture():
    data = bytearray(180)
    data[:16] = ptr_audio_v1.MAGIC
    struct.pack_into('>II', data, 16, 1, 24)
    struct.pack_into('>IIBBxxII', data, 24, 16, 18, 0, 0, 0, 48)
    struct.pack_into('>II16h', data, 48, 2, 1, *([0]*16))
    data[128:144] = ptr_audio.WAVES
    data[144:162] = (bytes([0])+bytes([0x11])*8)*2
    return data


def test_v1_bank_requires_complete_books_and_matching_frames():
    data = fixture()
    rows = ptr_audio_v1.regions(data)
    assert len(rows) == 1 and rows[0]['sample_count'] == 1
    assert rows[0]['rate_basis'] == 'Preview rate'
    assert ptr_audio_v1.preview(data, rows[0], {})['mime'] == 'audio/wav'
    data[144] = 1
    assert ptr_audio_v1.regions(data) == []
    data = fixture()
    struct.pack_into('>I', data, 40, 9000)
    assert ptr_audio_v1.bank(data, 0) is None
