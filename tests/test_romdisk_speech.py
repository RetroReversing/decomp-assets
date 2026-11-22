import struct
import zlib

from decompassets.n64 import romdisk, romdisk_speech


def fixture(compressed=False):
    clip = struct.pack('>4sHHII', b'MORT', 4, 12000, 4, 7)
    content = struct.pack('>II', 1, 8)+clip
    compressor = zlib.compressobj(wbits=-15)
    payload = compressor.compress(content)+compressor.flush() if compressed else content
    data = bytearray(256)
    data[:32] = romdisk.MAGIC
    struct.pack_into('>3I', data, 32, 64, 128, 1)
    data[64:64+len(payload)] = payload
    struct.pack_into('>I', data, 128, 132)
    struct.pack_into('>5I', data, 132, 0x20000000 if compressed else 0, len(payload), len(content), 64, 0)
    data[152:170] = b'/audio/voice.mdir\0'
    return data


def test_romdisk_bounds_and_speech_preview():
    for compressed in (False, True):
        data = fixture(compressed)
        groups = romdisk.members(data)
        assert len(groups) == 1 and len(groups[0]) == 1
        rows = romdisk_speech.regions(data)
        assert len(rows) == 1 and rows[0]['sample_count'] == 1
        assert rows[0]['table_confidence'] == 'validated'
        assert romdisk_speech.preview(data, rows[0], {})['mime'] == 'audio/wav'
        struct.pack_into('>I', data, 144, 255)
        assert romdisk.members(data) == []


def test_speech_offsets_and_header_must_match():
    clip = struct.pack('>4sHHII', b'MORT', 4, 12000, 4, 7)
    data = bytearray(struct.pack('>II', 1, 8)+clip)
    assert len(romdisk_speech.clips(data)) == 1
    data[8] = 0
    assert romdisk_speech.clips(data) == []
