import base64
import io
import struct
import wave

import pytest

from decompassets import formats
from decompassets.n64 import big_audio, big_models, big_sam_audio


def _block():
    return struct.pack('>hhB', 1, 100, 0) + b'\x1f' + bytes(62)


def _fixture():
    page = bytearray(8192)
    page[100:108] = b'idx\0' + struct.pack('<I', 44)
    struct.pack_into('>5I', page, 108, 2, 0, 0, 68, 0)
    struct.pack_into('>5I', page, 128, 0x12345678, 1, 68, 68, 1)
    page[300:308] = b'SAM\0' + struct.pack('<I', 36)
    struct.pack_into('>8I', page, 308, 5, 2, 0, 0, 16000, 0x80000000, 60, 32)
    page[340:344] = bytes.fromhex('52001f00')
    archive_size = 20 + len(page)
    archive = b'testBIG\0' + struct.pack('>I2I', len(page), 20 << 4, archive_size << 4) + page
    big_row = b'sfx.big\0'.ljust(16, b'\0') + struct.pack('>4I', 0, archive_size, 0, 0)
    raw_row = b'big.raw\0'.ljust(16, b'\0') + struct.pack('>4I', 0, 136, archive_size, 0)
    return big_row + raw_row + archive + _block() * 2


def test_indexed_streams_decode_and_use_the_requested_rate():
    image = _fixture()
    sounds = []
    assert not big_models.regions(image, audio=sounds)
    assert len(sounds) == 2
    bank = next(sound for sound in sounds if sound['layout'] == big_audio.LAYOUT)
    assert len(bank['samples']) == 2
    preview = big_audio.preview(image, bank, {'sample': 1, 'rate': 16000})
    payload = base64.b64decode(preview['data_url'].split(',')[1])
    with wave.open(io.BytesIO(payload), 'rb') as stream:
        assert stream.getframerate() == 16000 and stream.getnframes() == 128
        samples = struct.unpack('<4h', stream.readframes(4))
    assert samples == (0, 100, 107, 100)
    with pytest.raises(formats.AssetError):
        big_audio.preview(image, bank, {'sample': 2})


def test_malformed_predictors_and_mismatched_file_are_rejected():
    with pytest.raises(formats.AssetError):
        big_audio._block(_block()[:4] + b'\xff' + _block()[5:])
    image = bytearray(_fixture())
    struct.pack_into('>I', image, 32+20, 135)
    sounds = []
    big_models.regions(bytes(image), audio=sounds)
    assert not any(sound['layout'] == big_audio.LAYOUT for sound in sounds)


def test_tagged_sound_effect_uses_its_stored_rate():
    image = _fixture()
    sounds = []
    big_models.regions(image, audio=sounds)
    bank = next(sound for sound in sounds if sound['layout'] == big_sam_audio.LAYOUT)
    preview = big_sam_audio.preview(image, bank, {})
    payload = base64.b64decode(preview['data_url'].split(',')[1])
    with wave.open(io.BytesIO(payload), 'rb') as stream:
        assert stream.getframerate() == 16000
        assert struct.unpack('<2h', stream.readframes(2)) == (80, -71)
    with pytest.raises(formats.AssetError):
        big_sam_audio._decode(bytes.fromhex('57001f'), 2)
