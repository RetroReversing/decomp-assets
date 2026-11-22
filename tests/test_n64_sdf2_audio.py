import base64
import io
import struct
import wave

from decompassets.n64 import sdf2_audio


def _fixture():
    samples = (b'\x00\x11\x11\x11\x11\x11\x11\x11\x11', b'\x00\x22\x22\x22\x22\x22\x22\x22\x22')
    table_size = 16+2*24
    image = bytearray(table_size)
    struct.pack_into('>4sI4sI', image, 0, b'SDF2', table_size, b'BTEN', 2)
    for index, sample in enumerate(samples):
        relative = len(image)
        struct.pack_into('>6I', image, 16+24*index, len(sample), 0, 16, relative, 22050, 0)
        image.extend(bytes(160)+sample)
    return bytes(image)


def test_sample_directory_and_audio_preview():
    image = _fixture()
    assets = sdf2_audio.regions(image)
    assert len(assets) == 3
    assert len(assets[0]['samples']) == 2
    result = sdf2_audio.preview(image, assets[0], {'sample': 1})
    with wave.open(io.BytesIO(base64.b64decode(result['data_url'].split(',')[1]))) as stream:
        assert stream.getframerate() == 22050
        assert any(stream.readframes(16))


def test_invalid_offsets_and_predictors_rejected():
    image = bytearray(_fixture())
    struct.pack_into('>I', image, 16+12, 1)
    assert not sdf2_audio.regions(bytes(image))
    image = bytearray(_fixture())
    image[16+2*24+160] = 0x0f
    assert not sdf2_audio.regions(bytes(image))
