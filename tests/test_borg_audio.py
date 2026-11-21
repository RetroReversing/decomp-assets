import base64
import io
import struct
import wave

from decompassets.n64 import borg_audio


def test_borg_pcm8_converts_signed_samples_to_wav():
    blob = struct.pack('>4I', 0x14, 3, 3, 16)+bytes([0x80, 0, 0x7f])
    asset, = borg_audio.regions(blob, [(11, 0, len(blob), len(blob), 0)])
    result = borg_audio.preview(blob, asset, {})
    with wave.open(io.BytesIO(base64.b64decode(result['data_url'].split(',')[1]))) as decoded:
        assert decoded.getframerate() == 44100
        assert decoded.getsampwidth() == 1
        assert decoded.readframes(3) == bytes([0, 128, 255])
    assert borg_audio.sample(blob[:-1]) is None


def test_borg_pcm16_converts_big_endian_samples_to_wav():
    blob = struct.pack('>4I2h', 0x18, 4, 2, 16, -200, 300)
    asset, = borg_audio.regions(blob, [(11, 0, len(blob), len(blob), 0)])
    result = borg_audio.preview(blob, asset, {})
    with wave.open(io.BytesIO(base64.b64decode(result['data_url'].split(',')[1]))) as decoded:
        assert decoded.getsampwidth() == 2
        assert decoded.readframes(2) == struct.pack('<2h', -200, 300)
