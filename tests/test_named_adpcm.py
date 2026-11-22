import base64
import io
import struct
import wave

from decompassets.n64 import named_adpcm


def fixture():
    data = bytearray()
    for i, name in enumerate((b'one.wav', b'two.wav', b'three.wav')):
        data.extend(name+struct.pack('<II', 20*i, 20))
    data.extend(bytes((-len(data))%4))
    data.extend((bytes(4)+b'\x11\x11'*8)*3)
    return data


def test_named_directory_and_block_audio():
    data = fixture()
    asset, = named_adpcm.regions(data)
    assert len(asset['samples']) == 3
    result = named_adpcm.preview(data, asset, {})
    raw = base64.b64decode(result['data_url'].split(',')[1])
    with wave.open(io.BytesIO(raw)) as sound:
        assert sound.getnframes() == 32
        assert struct.unpack('<32h', sound.readframes(32)) == tuple(range(1, 33))
    data[7:11] = (9).to_bytes(4, 'little')
    assert not named_adpcm.regions(data)
